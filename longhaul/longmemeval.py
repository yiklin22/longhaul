"""LongMemEval (Wu et al., ICLR 2025) under a context strategy.

    inspect eval longhaul/longmemeval -T data=longmemeval_s.json -T strategy=edit -T threshold=60000 \\
        --model anthropic/claude-opus-5-5 --model-role grader=<judge model>

Get the data files from https://github.com/xiaowu0162/LongMemEval (MIT). They are not bundled here.

How this differs from the paper. The paper gives the model the whole chat history inside one prompt.
Here the history is REPLAYED as real conversation turns, session by session, and the context strategy
runs as the history grows, the way it would in a long-lived assistant. The final question is asked in
that same conversation. So `strategy=none` is close to the paper's full-history setting, but numbers
are not directly comparable with the paper's tables, and the other strategies have no counterpart there.

The judge prompts are the paper's own, copied from its `src/evaluation/evaluate_qa.py`, and a response
is marked correct when the judge's reply contains "yes", as in that script. The paper judged with
GPT-4o; set the `grader` model role (or `judge=`) to choose yours, and report which one you used.
"""
from __future__ import annotations

import json
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    CompactionStrategy,
    compaction,
    get_model,
)
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, grouped, scorer, stderr
from inspect_ai.solver import Generate, TaskState, solver

from .task import make_strategy

SYSTEM = ("You are a helpful assistant in a long-running conversation with one user. Earlier sessions are part of "
          "this conversation; each begins with its date. Use what the user told you in earlier sessions when it is "
          "relevant. If the conversation does not contain what a question asks for, say so instead of guessing.")
SUMMARY_INSTRUCTIONS = ("This is a long-running personal assistant conversation. Preserve every fact about the user "
                        "(events, preferences, numbers, names) with the date of the session it came from, and when "
                        "something changed keep both the old and the new value with their dates.")

_BASE = ("I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
         "contains the correct answer. Otherwise, answer no. ")
_TAIL = "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
_DEFAULT = (_BASE + "If the response is equivalent to the correct answer or contains all the intermediate steps to get "
            "the correct answer, you should also answer yes. If the response only contains a subset of the information "
            "required by the answer, answer no. " + _TAIL)
JUDGE = {
    "single-session-user": _DEFAULT,
    "single-session-assistant": _DEFAULT,
    "multi-session": _DEFAULT,
    "temporal-reasoning": (_BASE + "If the response is equivalent to the correct answer or contains all the intermediate "
                           "steps to get the correct answer, you should also answer yes. If the response only contains a "
                           "subset of the information required by the answer, answer no. In addition, do not penalize "
                           "off-by-one errors for the number of days. If the question asks for the number of "
                           "days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when "
                           "the answer is 18), the model's response is still correct. " + _TAIL),
    "knowledge-update": (_BASE + "If the response contains some previous information along with an updated answer, the "
                         "response should be considered as correct as long as the updated answer is the required answer."
                         + _TAIL),
    "single-session-preference": ("I will give you a question, a rubric for desired personalized response, and a response "
                                  "from a model. Please answer yes if the response satisfies the desired response. "
                                  "Otherwise, answer no. The model does not need to reflect all the points in the rubric. "
                                  "The response is correct as long as it recalls and utilizes the user's personal "
                                  "information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the "
                                  "model response correct? Answer yes or no only."),
}
JUDGE_ABSTENTION = ("I will give you an unanswerable question, an explanation, and a response from a model. Please answer "
                    "yes if the model correctly identifies the question as unanswerable. The model could say that the "
                    "information is incomplete, or some other information is given but the asked information is not."
                    "\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the "
                    "question as unanswerable? Answer yes or no only.")

_FILES: dict[str, dict[str, dict]] = {}


def load(path: str) -> dict[str, dict]:
    """Records by question id. Cached, because the files are large and every sample needs one record."""
    if path not in _FILES:
        _FILES[path] = {str(r["question_id"]): r for r in json.loads(Path(path).read_text())}
    return _FILES[path]


def is_abstention(question_id: str) -> bool:
    return "_abs" in question_id


def judge_prompt(question_type: str, question: str, answer: str, response: str, abstention: bool) -> str:
    if abstention:
        return JUDGE_ABSTENTION.format(question, answer, response)
    if question_type not in JUDGE:
        raise ValueError(f"unknown LongMemEval question type {question_type!r}")
    return JUDGE[question_type].format(question, answer, response)


def history_messages(record: dict) -> list[list[ChatMessage]]:
    """One list of chat messages per session, oldest session first, each opened by its date."""
    sessions = sorted(zip(record["haystack_dates"], record["haystack_sessions"]), key=lambda pair: pair[0])
    out = []
    for date, turns in sessions:
        messages: list[ChatMessage] = []
        for i, turn in enumerate(turns):
            text = turn["content"]
            if i == 0 and turn["role"] == "user":
                text = f"[Session date: {date}]\n{text}"
            elif i == 0:
                messages.append(ChatMessageUser(content=f"[Session date: {date}]"))
            messages.append(ChatMessageUser(content=text) if turn["role"] == "user" else ChatMessageAssistant(content=text))
        if messages:
            out.append(messages)
    return out


@solver
def replay(strategy: CompactionStrategy | None):
    async def solve(state: TaskState, generate_fn: Generate) -> TaskState:
        record = load(state.metadata["data"])[str(state.sample_id)]
        model = get_model()
        system = ChatMessageSystem(content=SYSTEM)
        messages: list[ChatMessage] = [system]
        compact = compaction(strategy, prefix=[system]) if strategy else None
        status = "ok"

        async def compacted(force: bool = False) -> list[ChatMessage]:
            model_input, summary = await compact.compact_input(messages, force=force)
            if summary:
                messages.append(summary)
            return model_input

        try:
            for session in history_messages(record):
                messages.extend(session)
                if compact:                               # the strategy runs as the history grows
                    await compacted()
            messages.append(ChatMessageUser(content=f"Current Date: {record['question_date']}\nQuestion: {record['question']}"))
            output = await model.generate(await compacted() if compact else messages)
            if output.stop_reason == "model_length" and compact:
                output = await model.generate(await compacted(force=True))
        except RuntimeError as err:                       # the strategy could not get under its threshold
            if "Compaction insufficient" not in str(err):
                raise
            status, output = "compaction_failed", None
        if output is not None:
            if output.stop_reason == "model_length":
                status = "context_overflow"
            elif output.stop_reason == "max_tokens":
                status = "truncated"
            messages.append(output.message)
            state.output = output
        state.messages = messages
        state.metadata["status"] = status
        return state

    return solve


@scorer(metrics=[accuracy(), stderr(), grouped(accuracy(), "question_type")])
def longmemeval_judge(judge: str | None = None):
    """The paper's yes/no judge. Uses `judge`, else the `grader` model role, else the model under test."""

    async def score(state: TaskState, target: Target) -> Score:
        meta = {"question_type": state.metadata["question_type"], "abstention": state.metadata["abstention"],
                "status": state.metadata.get("status", "ok")}
        response = state.output.completion if state.output else ""
        if meta["status"] in ("compaction_failed", "context_overflow") or not response.strip():
            return Score(value=INCORRECT, answer=response, explanation=f"no answer to judge ({meta['status']})", metadata=meta)
        grader = get_model(judge) if judge else get_model(role="grader")
        prompt = judge_prompt(meta["question_type"], state.input_text, target.text, response, meta["abstention"])
        verdict = (await grader.generate(prompt)).completion.strip()
        return Score(value=CORRECT if "yes" in verdict.lower() else INCORRECT, answer=response,
                     explanation=verdict, metadata=meta)

    return score


@task
def longmemeval(data: str, strategy: str = "none", threshold: int | float = 0.9, limit: int | None = None,
                question_types: str | None = None, keep_tool_uses: int = 3, preserve: float = 0.5,
                judge: str | None = None) -> Task:
    """LongMemEval with the history replayed as conversation turns under a context strategy.

    Args:
        data: Path to longmemeval_s.json, longmemeval_m.json or longmemeval_oracle.json.
        strategy: none | trim | edit | summary | native | auto (Inspect compaction strategies).
        threshold: Input tokens at which compaction triggers (int), or a fraction of the context window (float).
        limit: Use only the first N questions (after any type filter).
        question_types: Comma-separated question types to keep, for example "knowledge-update,multi-session".
        keep_tool_uses: For `edit`: recent tool results kept.
        preserve: For `trim`: share of messages kept.
        judge: Model that grades answers. Defaults to the `grader` model role.
    """
    keep = {t.strip() for t in question_types.split(",")} if question_types else None
    records = [r for r in load(data).values() if keep is None or r["question_type"] in keep]
    samples = [Sample(id=str(r["question_id"]), input=r["question"], target=str(r["answer"]),
                      metadata={"data": data, "question_type": r["question_type"],
                                "abstention": is_abstention(str(r["question_id"])), "question_date": r["question_date"]})
               for r in records[:limit]]
    return Task(
        dataset=samples,
        solver=replay(make_strategy(strategy, threshold, keep_tool_uses, preserve, False, SUMMARY_INSTRUCTIONS)),
        scorer=longmemeval_judge(judge),
        metadata={"strategy": strategy, "threshold": threshold, "benchmark": "LongMemEval"},
        name=f"longmemeval_{strategy}",
    )
