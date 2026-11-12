"""Cache-aware cost of an agent run, from the sequence of model calls in an Inspect log.

Two views of every call:

measured  the provider's own usage numbers (uncached input, cache write, cache read, output), when the
          log has them. This is the ground truth for a live run.
modelled  a prefix-cache simulation over the exact messages each call sent. It needs no API, so it
          prices a run offline, and on a live run it is a prediction to hold against the measured
          numbers: a call the model says should hit the cache but the provider billed as a miss points
          at a silent cache invalidator in the harness.

Cache rules modelled (Anthropic prompt caching): the cache key is the exact prefix up to a breakpoint;
breakpoints sit on the system prompt and on the last block; a breakpoint finds an earlier entry at most
`lookback` blocks back; a prefix shorter than `min_tokens` is not cached; an entry lives `ttl` seconds
from the start of the last request that wrote or read it; a request pays cache-read price up to the
longest hit, cache-write price from there to its last breakpoint, and full price for the rest.

Token counts in the modelled view are estimated as characters / `chars_per_token` (2.4, fitted to the
token counter Inspect uses offline on this workload; Claude's tokenizer tends to count more). That is an
approximation: every strategy is estimated the same way, so comparisons between strategies hold better
than the absolute dollar figures do. Prices are Anthropic's published first-party rates as cached on
2026-11-03; check the pricing page before budgeting on them.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Card:
    """USD per million tokens. `long_*` apply when the whole prompt is over `long_over` tokens."""
    input: float
    output: float
    cache_read: float
    cache_write: float               # 5-minute TTL
    long_over: int | None = None
    long_mult: float = 1.0
    min_cache_tokens: int = 512


CARDS = {
    "claude-fable-5-2": Card(8.00, 40.00, 0.20, 10.00),
    "claude-opus-5-5": Card(4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": Card(2.00, 10.00, 0.10, 2.50),
    # two rate cards chosen by prompt length: 5x above 100K prompt tokens
    "claude-haiku-5-5": Card(0.10, 0.50, 0.01, 0.125, long_over=100_000, long_mult=5.0),
}


@dataclass
class Call:
    uncached: int
    cache_write: int
    cache_read: int
    output: int

    @property
    def prompt(self) -> int:
        return self.uncached + self.cache_write + self.cache_read


def price(call: Call, card: Card) -> float:
    mult = card.long_mult if card.long_over and call.prompt > card.long_over else 1.0
    return mult * (call.uncached * card.input + call.cache_write * card.cache_write +
                   call.cache_read * card.cache_read + call.output * card.output) / 1e6


def estimate_tokens(text: str, chars_per_token: float = 2.4) -> int:
    return math.ceil(len(text) / chars_per_token)


def _block_text(message) -> str:
    """Everything in one message that is sent to the model, as stable text."""
    calls = getattr(message, "tool_calls", None) or []
    return message.role + "\n" + message.text + "".join(
        f"\n{c.function}{json.dumps(c.arguments, sort_keys=True)}" for c in calls)


def blocks_from_event(event, chars_per_token: float = 2.4) -> list[tuple[str, int]]:
    """(text, tokens) per cacheable block of one model call: tools + system first, then each message."""
    tools = json.dumps([t.model_dump() for t in (event.tools or [])], sort_keys=True, default=str)
    msgs = list(event.input)
    system = [m for m in msgs if m.role == "system"]
    head = tools + "".join(_block_text(m) for m in system)
    out = [(head, estimate_tokens(head, chars_per_token))]
    for m in msgs:
        if m.role != "system":
            text = _block_text(m)
            out.append((text, estimate_tokens(text, chars_per_token) + 4))
    return out


class PrefixCache:
    """Simulated prompt cache for one conversation."""

    def __init__(self, min_tokens: int = 512, lookback: int = 20, ttl: float = 300.0):
        self.min_tokens, self.lookback, self.ttl = min_tokens, lookback, ttl
        self.entries: dict[str, float] = {}

    def request(self, blocks: list[tuple[str, int]], output_tokens: int, now: float, caching: bool = True) -> Call:
        chain, cum, h, total = [], [], hashlib.sha256(), 0
        for text, tokens in blocks:
            h.update(text.encode() + b"\x00")
            total += tokens
            chain.append(h.hexdigest())
            cum.append(total)
        if not caching:
            return Call(total, 0, 0, output_tokens)
        last = len(blocks) - 1
        breakpoints = sorted({0, last})
        hit = -1
        for bp in breakpoints:
            for k in range(bp, max(bp - self.lookback, -1), -1):
                if cum[k] >= self.min_tokens and self.entries.get(chain[k], -1.0) > now:
                    hit = max(hit, k)
                    break
        read = cum[hit] if hit >= 0 else 0
        write = cum[last] - read if cum[last] >= self.min_tokens else 0
        if hit >= 0:
            self.entries[chain[hit]] = now + self.ttl                  # a read refreshes the entry
        for bp in breakpoints:
            if cum[bp] >= self.min_tokens:
                self.entries[chain[bp]] = now + self.ttl
        return Call(total - read - write, write, read, output_tokens)


def sample_calls(sample, chars_per_token: float = 2.4, gap_s: float | None = 10.0, ttl: float = 300.0,
                 min_tokens: int = 512) -> dict:
    """Modelled (cached and uncached) and measured calls for one sample of an Inspect log.

    gap_s: seconds assumed between calls for the cache lifetime. None uses the log's own timestamps,
    which is right for a live run and meaningless for a mock run that finishes in milliseconds.
    """
    cache = PrefixCache(min_tokens=min_tokens, ttl=ttl)
    modelled, uncached, measured = [], [], []
    clock = 0.0
    for event in sample.events:
        if event.event != "model" or event.output is None or event.error:
            continue
        blocks = blocks_from_event(event, chars_per_token)
        out_text = _block_text(event.output.message) if event.output.choices else ""
        out_tokens = estimate_tokens(out_text, chars_per_token)
        now = event.timestamp.timestamp() if gap_s is None else clock
        clock += gap_s or 0.0
        modelled.append(cache.request(blocks, out_tokens, now))
        uncached.append(Call(sum(t for _, t in blocks), 0, 0, out_tokens))
        usage = event.output.usage
        if usage and (usage.input_tokens_cache_read is not None or usage.input_tokens_cache_write is not None):
            measured.append(Call(usage.input_tokens, usage.input_tokens_cache_write or 0,
                                 usage.input_tokens_cache_read or 0, usage.output_tokens))
    return {"modelled": modelled, "uncached": uncached, "measured": measured}


def summarise(calls: list[Call]) -> dict:
    prompt = sum(c.prompt for c in calls)
    return {
        "calls": len(calls),
        "prompt_tokens": prompt,
        "peak_prompt": max((c.prompt for c in calls), default=0),
        "cache_read_share": (sum(c.cache_read for c in calls) / prompt) if prompt else 0.0,
        "cost": {name: sum(price(c, card) for c in calls) for name, card in CARDS.items()},
    }
