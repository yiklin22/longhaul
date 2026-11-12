"""LongMemEval adapter on a tiny made-up file in the benchmark's format. No benchmark data is bundled."""
import json
import tempfile
import unittest
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import resolve_sample_attachments
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model

from longhaul.cost import sample_calls
from longhaul.longmemeval import history_messages, is_abstention, judge_prompt, longmemeval

FILLER = "Tell me something about tide tables and how harbour pilots read them. " * 40


def record(qid, qtype, question, answer, evidence):
    filler = [{"role": "user", "content": FILLER}, {"role": "assistant", "content": "Here is an overview. " * 30}]
    # The evidence is the SECOND session: Inspect's trim always keeps the first user message.
    sessions = [filler, [{"role": "user", "content": evidence, "has_answer": True}, {"role": "assistant", "content": "Got it."}]]
    sessions += [filler for _ in range(7)]
    dates = [f"2023/05/{d:02d} (Mon) 10:00" for d in range(1, 10)]
    return {"question_id": qid, "question_type": qtype, "question": question, "answer": answer,
            "question_date": "2023/06/01 (Thu) 09:00", "haystack_session_ids": [f"s{i}" for i in range(9)],
            "haystack_dates": dates, "haystack_sessions": sessions, "answer_session_ids": ["s1"]}


RECORDS = [
    record("q1", "single-session-user", "What colour is my bicycle?", "teal", "By the way, my bicycle is teal."),
    record("q2", "knowledge-update", "Which city do I live in now?", "Leeds", "I have just moved from York to Leeds."),
    record("q3_abs", "multi-session", "What is my sister's name?", "The user never mentioned a sister.", "I enjoy sailing."),
]
NEEDLES = {"bicycle": ("my bicycle is teal", "Your bicycle is teal."), "city": ("moved from York to Leeds", "You live in Leeds."),
           "sister": ("NEVER PRESENT", "")}


def mock(messages, tools, tool_choice, config) -> ModelOutput:
    """Answers from the visible history only; judges by simple containment; writes empty summaries."""
    last = [m for m in messages if isinstance(m, ChatMessageUser)][-1].text
    if last.startswith("I will give you"):
        response = last.split("Model Response: ")[1].split("\n\n")[0]
        if "unanswerable" in last:
            return ModelOutput.from_content("mockllm/model", "yes" if "do not have" in response else "no")
        gold = last.split("Correct Answer: ")[1].split("\n\n")[0]
        return ModelOutput.from_content("mockllm/model", "yes" if gold.lower() in response.lower() else "no")
    if "Question:" not in last:
        return ModelOutput.from_content("mockllm/model", "Summary: nothing to carry forward.")
    visible = "\n".join(m.text for m in messages if isinstance(m, ChatMessageUser))
    for key, (needle, answer) in NEEDLES.items():
        if key in last:
            return ModelOutput.from_content("mockllm/model", answer if needle in visible else "I do not have that information.")
    return ModelOutput.from_content("mockllm/model", "I do not have that information.")


class LongMemEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.data = str(Path(cls.tmp.name) / "tiny.json")
        Path(cls.data).write_text(json.dumps(RECORDS))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_task(self, **kw):
        log = inspect_eval(longmemeval(data=self.data, **kw), model=get_model("mockllm/model", custom_outputs=mock),
                           model_roles={"grader": get_model("mockllm/model", custom_outputs=mock)},
                           log_dir=self.tmp.name, display="none")[0]
        self.assertEqual(log.status, "success", log.error)
        return log

    def test_sessions_are_replayed_oldest_first_with_their_dates(self):
        shuffled = dict(RECORDS[0], haystack_dates=RECORDS[0]["haystack_dates"][::-1], haystack_sessions=RECORDS[0]["haystack_sessions"][::-1])
        sessions = history_messages(shuffled)
        self.assertEqual(len(sessions), 9)
        self.assertTrue(sessions[0][0].text.startswith("[Session date: 2023/05/01"))
        self.assertTrue(sessions[1][0].text.startswith("[Session date: 2023/05/02"))
        self.assertIn("my bicycle is teal", sessions[1][0].text)

    def test_judge_prompt_follows_the_question_type(self):
        self.assertIn("off-by-one", judge_prompt("temporal-reasoning", "q", "a", "r", False))
        self.assertIn("updated answer", judge_prompt("knowledge-update", "q", "a", "r", False))
        self.assertIn("Rubric", judge_prompt("single-session-preference", "q", "a", "r", False))
        self.assertIn("unanswerable", judge_prompt("multi-session", "q", "a", "r", True))
        self.assertTrue(is_abstention("q3_abs") and not is_abstention("q1"))
        with self.assertRaises(ValueError):
            judge_prompt("made-up", "q", "a", "r", False)

    def test_full_history_answers_everything(self):
        log = self.run_task(strategy="none")
        self.assertEqual(log.results.scores[0].metrics["accuracy"].value, 1.0)
        self.assertIn("knowledge-update", log.results.scores[0].metrics)

    def test_trimming_drops_the_early_evidence_but_not_the_abstention(self):
        log = self.run_task(strategy="trim", threshold=1500, preserve=0.3)
        by_id = {s.id: s.scores["longmemeval_judge"].value for s in log.samples}
        self.assertEqual(by_id, {"q1": "I", "q2": "I", "q3_abs": "C"})

    def test_filters_and_limit(self):
        log = self.run_task(question_types="knowledge-update")
        self.assertEqual([s.id for s in log.samples], ["q2"])
        self.assertEqual(len(self.run_task(limit=2).samples), 2)

    def test_cost_model_reads_these_logs_too(self):
        calls = sample_calls(resolve_sample_attachments(self.run_task(strategy="none").samples[0], "full"), gap_s=10.0)
        self.assertEqual(len(calls["modelled"]), 2)                      # the answer, then the judge
        self.assertGreater(calls["modelled"][0].prompt, 3000)


if __name__ == "__main__":
    unittest.main()
