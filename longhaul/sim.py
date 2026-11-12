"""Offline run: every strategy against the perfect-reader mock. No API key, no cost.

    python -m longhaul.sim --out docs/results/offline.md

What this measures is real but narrow:
  evidence survival   the share of probes whose evidence is still in the context the strategy sends.
                      No model can beat it, so it is an upper bound on memory accuracy.
  modelled cost       the price of the exact prompts each strategy sent, with and without prompt caching.
It says nothing about how well a real model reads a long context or writes a summary; that needs a live run.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.model import get_model

from .oracle import make_mock
from .report import arm_stats, render
from .task import REGISTRY, longhaul

ARMS = [
    ("none (full history)", {"strategy": "none"}),
    ("trim, keep 50%", {"strategy": "trim", "preserve": 0.5}),
    ("edit, keep 3 tool results", {"strategy": "edit", "keep_tool_uses": 3}),
    ("summary", {"strategy": "summary"}),
    ("trim + memory tool", {"strategy": "trim", "preserve": 0.5, "memory": True}),
    ("edit + memory tool", {"strategy": "edit", "keep_tool_uses": 3, "memory": True}),
]


def run(kind: str, turns: int, seeds: int, threshold: int, noise_chars: int, per_category: int, gap: float) -> list[dict]:
    arms = []
    with tempfile.TemporaryDirectory(prefix="longhaul-") as tmp:
        for label, params in ARMS:
            task = longhaul(threshold=threshold, turns=turns, seeds=seeds, noise_chars=noise_chars,
                            per_category=per_category, **params)
            model = get_model("mockllm/model", custom_outputs=make_mock(kind, REGISTRY))
            log = inspect_eval(task, model=model, log_dir=tmp, display="none")[0]
            if log.status != "success":
                raise RuntimeError(f"{label}: {log.status} {log.error}")
            arm = arm_stats(log, gap_s=gap)
            arm["label"] = label
            if params["strategy"] == "summary" or params.get("memory"):
                # The mock summariser and note-taker copy facts verbatim, so their score is true by construction, not a finding.
                arm["accuracy_override"] = "needs a live run"
            arms.append(arm)
    return arms


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turns", type=int, default=120)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--threshold", type=int, default=30000)
    ap.add_argument("--noise-chars", type=int, default=2400)
    ap.add_argument("--per-category", type=int, default=4)
    ap.add_argument("--gap", type=float, default=10.0, help="assumed seconds between model calls (cache lifetime is 300)")
    ap.add_argument("--mock", default="oracle", choices=["oracle", "gullible", "null"])
    ap.add_argument("--out")
    args = ap.parse_args()
    arms = run(args.mock, args.turns, args.seeds, args.threshold, args.noise_chars, args.per_category, args.gap)
    header = (f"# Offline results ({args.mock} mock)\n\n"
              f"{args.seeds} shifts of {args.turns} turns, about {args.noise_chars} characters of ticket text per routine turn, "
              f"compaction threshold {args.threshold:,} tokens, {args.gap:g} s between calls. "
              "Token counts are estimated (characters / 2.4, fitted to the offline token counter; Claude's tokenizer tends to count more, so treat dollar figures as a floor); prices are per shift.\n\n"
              "**Read the accuracy column as evidence survival**: the share of probes whose evidence was still in the "
              "prompt, scored by a mock that reads perfectly. It is an upper bound for any real model, not a model result.\n\n")
    text = header + render(arms, "evidence survival")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
