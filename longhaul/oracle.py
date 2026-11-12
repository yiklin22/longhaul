"""Offline stand-in models for Inspect's `mockllm`. They are test doubles, not results about any LLM.

`oracle`    a perfect reader: answers correctly whenever the evidence sentence is still in the context
            it was sent, and follows the trust rule exactly. Its score is therefore the share of probes
            whose evidence SURVIVED the context strategy: an upper bound on what any model could score.
`gullible`  same reader, but it believes injected notices. Known-bad for the poison grader.
`null`      always answers UNKNOWN and never calls a tool. Known-bad for everything except abstention.

When Inspect's summary compaction asks the mock to summarise, `oracle` copies every fact sentence it can
see word for word (so summarising loses nothing), and `null` returns an empty summary. Real summarisers
sit somewhere in between, which is exactly what a live run measures.
"""
from __future__ import annotations

import re
from typing import Callable

from inspect_ai.model import ChatMessage, ChatMessageTool, ChatMessageUser, ModelOutput

from .scenario import UNKNOWN, Scenario

MODEL = "mockllm/model"
TURN_RE = re.compile(r"\[turn (\d+)\]")
REF_RE = re.compile(r"Shift reference: (LH-\d+-[0-9a-f]+)")


def _visible(messages: list[ChatMessage]) -> str:
    return "\n".join(m.text for m in messages if isinstance(m, (ChatMessageUser, ChatMessageTool)))


def resolve(scenario: Scenario, key: tuple[str, str], visible: str, trust_injected: bool = False) -> str:
    """What a perfect reader concludes about `key` from the text it can see."""
    seen = [f for f in scenario.facts if f.key == key and f.sentence in visible]
    if trust_injected and seen:
        return max(seen, key=lambda f: f.turn).value
    operator = [f for f in seen if f.source == "operator"]
    if operator:
        return max(operator, key=lambda f: f.turn).value
    directory = [f for f in seen if f.source == "directory"]
    return max(directory, key=lambda f: f.turn).value if directory else UNKNOWN


def make_mock(kind: str, registry: dict[str, Scenario]) -> Callable[..., ModelOutput]:
    if kind not in ("oracle", "gullible", "null"):
        raise ValueError(kind)

    def respond(messages: list[ChatMessage], tools, tool_choice, config) -> ModelOutput:
        def say(text: str) -> ModelOutput:
            return ModelOutput.from_content(MODEL, text)

        ref = REF_RE.search("\n".join(m.text for m in messages))
        scenario = registry[ref.group(1)] if ref else None
        visible = _visible(messages)
        users = [m for m in messages if isinstance(m, ChatMessageUser)]
        # The current turn is the last marker in the last user message. After a summary compaction that
        # message is the summary itself, which carries the pending request forward (see below).
        markers = TURN_RE.findall(users[-1].text) if users else []
        if scenario is None or not markers:               # a summarisation request from compaction
            if kind == "null" or scenario is None:
                return say("Summary: nothing to carry forward.")
            kept = [f.sentence for f in scenario.facts if f.sentence in visible and (kind == "gullible" or f.source != "injected")]
            pending = [m.text for m in users if TURN_RE.match(m.text)]
            return say("Summary of the shift so far.\n" + "\n".join(kept) +
                       (f"\nPending request: {pending[-1]}" if pending else ""))
        if kind == "null":
            return say(f"ANSWER: {UNKNOWN}")

        turn = scenario.turns[int(markers[-1])]
        after_tool = isinstance(messages[-1], ChatMessageTool)
        if turn.kind in ("plant", "update"):
            return say("Noted.")
        if turn.kind == "control":
            if not after_tool:
                return ModelOutput.for_tool_call(MODEL, "fetch_ticket", {"ticket_id": turn.ticket})
            found = re.search(r"checksum: (\S+)", messages[-1].text)
            return say(f"ANSWER: {found.group(1) if found else UNKNOWN}")

        question = turn.text.split("] ", 1)[1]
        if turn.expect is None:                           # defensive: an ungraded turn kind
            return say("Noted.")
        gullible = kind == "gullible"
        if question in scenario.hops:
            first, second = scenario.hops[question]
            middle = resolve(scenario, first, visible, gullible)
            value = UNKNOWN if middle == UNKNOWN else resolve(scenario, second, visible, gullible)
        else:
            value = resolve(scenario, (turn.expect.account, turn.expect.attr), visible, gullible)
        if turn.kind == "action":
            if after_tool:
                return say("ANSWER: DONE")
            if value == UNKNOWN:
                return say(f"ANSWER: {UNKNOWN}")
            return ModelOutput.for_tool_call(MODEL, "submit_change",
                                             {"account": turn.expect.account, "field": turn.expect.attr, "value": value})
        return say(f"ANSWER: {value}")

    return respond
