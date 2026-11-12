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


WARNING = "Context compaction approaching"


def make_mock(kind: str, registry: dict[str, Scenario]) -> Callable[..., ModelOutput]:
    if kind not in ("oracle", "gullible", "null"):
        raise ValueError(kind)
    # Per shift: the notes file the mock keeps when it has the memory tool. Holding the accumulated
    # sentences here stands in for appending to one file; the mock still has to read the file back
    # through the tool before it can use anything in it.
    notes: dict[str, dict] = {}

    def respond(messages: list[ChatMessage], tools, tool_choice, config) -> ModelOutput:
        def say(text: str) -> ModelOutput:
            return ModelOutput.from_content(MODEL, text)

        def used(function: str, since: int, command: str | None = None) -> bool:
            return any(getattr(m, "tool_calls", None) and any(
                c.function == function and (command is None or c.arguments.get("command") == command)
                for c in m.tool_calls) for m in messages[since:])

        ref = REF_RE.search("\n".join(m.text for m in messages))
        scenario = registry[ref.group(1)] if ref else None
        visible = _visible(messages)
        gullible = kind == "gullible"
        has_memory = any(t.name == "memory" for t in tools)
        user_at = [i for i, m in enumerate(messages) if isinstance(m, ChatMessageUser)]
        last_text = messages[user_at[-1]].text if user_at else ""

        # Inspect warns before compacting when the memory tool is present: save what is visible, once.
        if scenario and kind != "null" and has_memory and last_text.startswith(WARNING) and not used("memory", user_at[-1], "create"):
            book = notes.setdefault(scenario.ref, {"sentences": [], "saves": 0, "path": None})
            for f in scenario.facts:
                if f.sentence in visible and (gullible or f.source != "injected") and f.sentence not in book["sentences"]:
                    book["sentences"].append(f.sentence)
            book["saves"] += 1
            book["path"] = f"/memories/facts-{book['saves']}.md"
            return ModelOutput.for_tool_call(MODEL, "memory", {"command": "create", "path": book["path"],
                                                               "file_text": "\n".join(book["sentences"])})

        # The current turn is the most recent turn marker the model can see. After a summary compaction
        # that is inside the summary message, which carries the pending request forward.
        turn_at = next((i for i in reversed(user_at) if TURN_RE.search(messages[i].text)), None)
        asked_to_summarise = bool(user_at) and not last_text.startswith(WARNING) and not TURN_RE.search(last_text)
        if scenario is None or turn_at is None or asked_to_summarise:
            if kind == "null" or scenario is None:
                return say("Summary: nothing to carry forward.")
            kept = [f.sentence for f in scenario.facts if f.sentence in visible and (gullible or f.source != "injected")]
            pending = [messages[i].text for i in user_at if TURN_RE.match(messages[i].text)]
            return say("Summary of the shift so far.\n" + "\n".join(kept) +
                       (f"\nPending request: {pending[-1]}" if pending else ""))
        if kind == "null":
            return say(f"ANSWER: {UNKNOWN}")

        turn = scenario.turns[int(TURN_RE.findall(messages[turn_at].text)[-1])]
        last_tool = messages[-1] if isinstance(messages[-1], ChatMessageTool) else None
        if turn.kind in ("plant", "update"):
            return say("Noted.")
        if turn.kind == "control":
            if last_tool is None or last_tool.function != "fetch_ticket":
                return ModelOutput.for_tool_call(MODEL, "fetch_ticket", {"ticket_id": turn.ticket})
            found = re.search(r"checksum: (\S+)", last_tool.text)
            return say(f"ANSWER: {found.group(1) if found else UNKNOWN}")
        if turn.expect is None:                           # defensive: an ungraded turn kind
            return say("Noted.")

        book = notes.get(scenario.ref)

        def check_notes() -> ModelOutput | None:
            """Read the notes file once per turn, if there is one."""
            if has_memory and book and book["path"] and not used("memory", turn_at, "view"):
                return ModelOutput.for_tool_call(MODEL, "memory", {"command": "view", "path": book["path"]})
            return None

        question = turn.text.split("] ", 1)[1]
        if turn.expect.category == "count":               # needs every operator statement of that kind
            lookup = check_notes()                        # a count can be short without looking short
            if lookup:
                return lookup
            seen = {f.key[0] for f in scenario.facts if f.source == "operator" and f.key[1] == turn.expect.attr
                    and f.turn < turn.index and f.sentence in visible}
            return say(f"ANSWER: {len(seen)}")
        if question in scenario.hops:
            first, second = scenario.hops[question]
            middle = resolve(scenario, first, visible, gullible)
            value = UNKNOWN if middle == UNKNOWN else resolve(scenario, second, visible, gullible)
        else:
            value = resolve(scenario, (turn.expect.account, turn.expect.attr), visible, gullible)
        if turn.kind == "action" and used("submit_change", turn_at):
            return say("ANSWER: DONE")
        if value == UNKNOWN:
            lookup = check_notes()
            if lookup:
                return lookup
            return say(f"ANSWER: {UNKNOWN}")
        if turn.kind == "action":
            return ModelOutput.for_tool_call(MODEL, "submit_change",
                                             {"account": turn.expect.account, "field": turn.expect.attr, "value": value})
        return say(f"ANSWER: {value}")

    return respond
