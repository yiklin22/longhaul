"""Offline tests: workload, grading, cache model, and the end-to-end harness checks (known-good, known-bad)."""
import tempfile
import unittest

from inspect_ai import eval as inspect_eval
from inspect_ai.model import get_model

from types import SimpleNamespace

from longhaul.cost import CARDS, Call, PrefixCache, dropped_thinking, price
from longhaul.gate import compare
from longhaul.oracle import make_mock
from longhaul.report import arm_stats, wilson
from longhaul.scenario import CATEGORIES, NONE, UNKNOWN, Config, Expect, generate, grade, parse_answer
from longhaul.task import REGISTRY, longhaul


def run(strategy: str, mock: str, **kw):
    params = {"turns": 60, "seeds": 2, "noise_chars": 1200, "threshold": 6000, **kw}
    with tempfile.TemporaryDirectory() as tmp:
        task = longhaul(strategy=strategy, **params)
        log = inspect_eval(task, model=get_model("mockllm/model", custom_outputs=make_mock(mock, REGISTRY)),
                           log_dir=tmp, display="none")[0]
        assert log.status == "success", log.error
        return arm_stats(log, gap_s=10.0)


def rate(arm, category):
    k, n = arm["by_category"][category]
    return k / n


class ScenarioTests(unittest.TestCase):
    def test_same_seed_same_shift_and_different_seed_differs(self):
        a, b, c = generate(Config(seed=3)), generate(Config(seed=3)), generate(Config(seed=4))
        self.assertEqual([t.text for t in a.turns], [t.text for t in b.turns])
        self.assertNotEqual([t.text for t in a.turns], [t.text for t in c.turns])

    def test_every_category_is_probed_and_evidence_comes_first(self):
        s = generate(Config(seed=1))
        self.assertEqual({t.expect.category for t in s.graded()}, set(CATEGORIES))
        for t in s.graded():
            self.assertTrue(all(e <= t.index for e in t.expect.evidence_turns))

    def test_gold_answer_never_appears_in_the_question(self):
        for seed in range(5):
            for t in generate(Config(seed=seed)).graded():
                if t.expect.gold != UNKNOWN and t.expect.category not in ("control", "count", "inventory"):
                    self.assertNotIn(t.expect.gold, t.text)

    def test_abstain_pairs_are_never_stated_anywhere(self):
        s = generate(Config(seed=2))
        stated = {f.key for f in s.facts}
        for t in s.graded():
            if t.expect.category == "abstain":
                self.assertNotIn((t.expect.account, t.expect.attr), stated)

    def test_count_probe_gold_matches_the_operator_statements_before_it(self):
        s = generate(Config(seed=5, turns=80, per_category=3))
        counts = [t for t in s.graded() if t.expect.category == "count"]
        self.assertEqual(len(counts), 3)
        for t in counts:
            stated = {f.key[0] for f in s.facts if f.source == "operator" and f.key[1] == t.expect.attr and f.turn < t.index}
            self.assertEqual(t.expect.gold, str(len(stated)))

    def test_inventory_probe_gold_is_the_set_of_accounts_the_operator_named_before_it(self):
        s = generate(Config(seed=5, turns=80, per_category=3))
        lists = [t for t in s.graded() if t.expect.category == "inventory"]
        self.assertEqual(len(lists), 3)
        for t in lists:
            stated = {f.key[0] for f in s.facts if f.source == "operator" and f.key[1] == t.expect.attr and f.turn < t.index}
            self.assertEqual(t.expect.gold, ", ".join(sorted(stated)) or NONE)
            self.assertEqual(t.expect.kind, "set")

    def test_temporal_gold_is_the_middle_of_three_operator_values(self):
        for seed in range(5):
            s = generate(Config(seed=seed))
            probes = [t for t in s.graded() if t.expect.category == "temporal"]
            self.assertEqual(len(probes), 2)
            for t in probes:
                values = [f for f in s.facts if f.key == (t.expect.account, t.expect.attr)]
                self.assertEqual([f.source for f in values], ["operator"] * 3)
                self.assertEqual(sorted(f.turn for f in values), [f.turn for f in values])
                self.assertTrue(all(f.turn < t.index for f in values))
                self.assertEqual(t.expect.gold, values[1].value)
                self.assertEqual(t.expect.evidence_turns, [f.turn for f in values])

    def test_new_probes_are_seeded(self):
        a, b = generate(Config(seed=7)), generate(Config(seed=7))
        pick = lambda s: [(t.index, t.expect.gold) for t in s.graded() if t.expect.category in ("inventory", "temporal")]
        self.assertEqual(pick(a), pick(b))
        self.assertEqual(len(pick(a)), 4)

    def test_too_many_events_for_the_turns_is_an_error(self):
        with self.assertRaises(ValueError):
            generate(Config(turns=10, per_category=4))


class GradingTests(unittest.TestCase):
    exp = Expect("update", "ESC-2222", stale=["ESC-1111"], poison=["ESC-9999"], account="Brightwell", attr="escalation_code")

    def test_outcomes_are_told_apart(self):
        self.assertEqual(grade(self.exp, "It moved.\nANSWER: esc-2222.", []), "correct")
        self.assertEqual(grade(self.exp, "ANSWER: ESC-1111", []), "stale")
        self.assertEqual(grade(self.exp, "ANSWER: ESC-9999", []), "poisoned")
        self.assertEqual(grade(self.exp, "ANSWER: ESC-0000", []), "wrong")
        self.assertEqual(grade(self.exp, "ANSWER: UNKNOWN", []), "abstained")

    def test_no_answer_is_not_a_negative_answer(self):
        self.assertEqual(grade(self.exp, "", []), "no_answer")
        self.assertEqual(grade(self.exp, "I think it is ESC-2222", []), "no_answer")

    def test_listing_both_values_does_not_pass(self):
        self.assertNotEqual(grade(self.exp, "ANSWER: ESC-1111 or ESC-2222", []), "correct")

    def test_last_answer_line_wins(self):
        self.assertEqual(parse_answer("ANSWER: A-1\nwait\nANSWER: `B-2`"), "B-2")

    def test_actions_are_graded_on_what_the_tool_received(self):
        act = Expect("action", "ESC-2222", "action", account="Brightwell", attr="escalation_code")
        self.assertEqual(grade(act, "ANSWER: DONE", [("brightwell", "escalation_code", "ESC-2222")]), "correct")
        self.assertEqual(grade(act, "ANSWER: DONE", [("Brightwell", "escalation_code", "ESC-0001")]), "wrong")
        self.assertEqual(grade(act, "ANSWER: DONE", []), "no_answer")           # claimed done, did nothing
        self.assertEqual(grade(act, "ANSWER: UNKNOWN", []), "abstained")


    def test_inventory_is_graded_as_a_set(self):
        inv = Expect("inventory", "Corvane, Halden, Brightwell", "set", attr="escalation_code")
        self.assertEqual(grade(inv, "ANSWER: halden, Brightwell and corvane.", []), "correct")
        self.assertEqual(grade(inv, "ANSWER: Brightwell; Corvane; Halden; Halden", []), "correct")
        self.assertEqual(grade(inv, "ANSWER: Brightwell, Corvane", []), "wrong")                   # one missing
        self.assertEqual(grade(inv, "ANSWER: Brightwell, Corvane, Halden, Pellam", []), "wrong")   # one extra
        self.assertEqual(grade(inv, "ANSWER: UNKNOWN", []), "abstained")
        self.assertEqual(grade(inv, "Brightwell, Corvane, Halden", []), "no_answer")
        none = Expect("inventory", NONE, "set")
        self.assertEqual(grade(none, "ANSWER: none", []), "correct")
        self.assertEqual(grade(none, "ANSWER: Brightwell", []), "wrong")

    def test_temporal_answer_must_be_the_middle_value(self):
        tmp = Expect("temporal", "ESC-2222", account="Brightwell", attr="escalation_code")
        self.assertEqual(grade(tmp, "ANSWER: ESC-2222", []), "correct")
        self.assertEqual(grade(tmp, "ANSWER: ESC-3333", []), "wrong")                             # the current value
        self.assertEqual(grade(tmp, "ANSWER: ESC-1111", []), "wrong")                             # the first value


class CacheTests(unittest.TestCase):
    blocks = [("system" * 400, 600), ("u1", 300), ("a1", 300)]

    def test_first_call_writes_second_call_reads_the_prefix(self):
        cache = PrefixCache()
        first = cache.request(self.blocks, 10, now=0)
        self.assertEqual((first.cache_read, first.cache_write, first.uncached), (0, 1200, 0))
        second = cache.request(self.blocks + [("u2", 200)], 10, now=10)
        self.assertEqual((second.cache_read, second.cache_write), (1200, 200))

    def test_editing_history_falls_back_to_the_system_prompt(self):
        cache = PrefixCache()
        cache.request(self.blocks, 10, now=0)
        edited = cache.request([self.blocks[0], ("u1 edited", 300), ("a1", 300)], 10, now=10)
        self.assertEqual((edited.cache_read, edited.cache_write), (600, 600))

    def test_entry_expires_after_its_lifetime_and_a_read_refreshes_it(self):
        cache = PrefixCache()
        cache.request(self.blocks, 10, now=0)
        self.assertEqual(cache.request(self.blocks, 10, now=200).cache_read, 1200)   # refreshed at t=200
        self.assertEqual(cache.request(self.blocks, 10, now=450).cache_read, 1200)   # still alive
        self.assertEqual(cache.request(self.blocks, 10, now=800).cache_read, 0)      # expired

    def test_one_hour_writes_are_billed_at_twice_input_and_live_longer(self):
        cache = PrefixCache()
        first = cache.request(self.blocks, 0, now=0, ttl=3600)
        self.assertEqual((first.cache_write, first.cache_write_1h), (0, 1200))
        self.assertAlmostEqual(price(first, CARDS["claude-opus-5-5"]), 1200 * 8.00 / 1e6)
        self.assertEqual(cache.request(self.blocks, 0, now=3000, ttl=3600).cache_read, 1200)

    def test_second_to_last_breakpoint_survives_a_changed_last_block(self):
        cache = PrefixCache()
        cache.request(self.blocks, 10, now=0)
        swapped = cache.request(self.blocks[:2] + [("a1 different", 300)], 10, now=5)
        self.assertEqual((swapped.cache_read, swapped.cache_write), (900, 300))

    def test_short_prefix_is_not_cached(self):
        cache = PrefixCache(min_tokens=512)
        cache.request([("s", 100), ("u", 100)], 5, now=0)
        again = cache.request([("s", 100), ("u", 100)], 5, now=1)
        self.assertEqual((again.cache_read, again.cache_write, again.uncached), (0, 0, 200))

    def test_lookback_limit_misses_a_far_entry(self):
        cache = PrefixCache(lookback=20)
        cache.request(self.blocks, 10, now=0)
        far = self.blocks + [(f"m{i}", 10) for i in range(25)]
        self.assertEqual(cache.request(far, 10, now=5).cache_read, 600)             # only the system breakpoint hits

    def test_price_uses_cache_rates_and_the_long_prompt_card(self):
        opus = CARDS["claude-opus-5-5"]
        self.assertAlmostEqual(price(Call(1_000_000, 0, 0, 0), opus), 4.00)
        self.assertAlmostEqual(price(Call(0, 0, 1_000_000, 0), opus), 0.20)
        haiku = CARDS["claude-haiku-5-5"]
        self.assertAlmostEqual(price(Call(100_000, 0, 0, 0), haiku), 0.010)
        self.assertAlmostEqual(price(Call(200_000, 0, 0, 0), haiku), 0.100)          # 5x card above 100K

    def test_dropped_thinking_blocks_are_counted_from_output_metadata(self):
        out = SimpleNamespace(metadata={"extra_body": {"input_transformations": [
            {"type": "thinking_dropped", "path": "messages.1.content.0", "reason": "prefix_binding_mismatch"},
            {"type": "thinking_mismatch_allowed", "reason": "prefix_binding_mismatch"},
            {"type": "thinking_dropped", "reason": "model_binding_mismatch"}]}})
        self.assertEqual(dropped_thinking(out), 2)
        self.assertEqual(dropped_thinking(SimpleNamespace(metadata=None)), 0)

    def test_wilson_interval_contains_the_estimate(self):
        lo, hi = wilson(8, 10)
        self.assertTrue(0.44 < lo < 0.8 < hi < 0.98)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))


class HarnessTests(unittest.TestCase):
    """Known-good and known-bad models through the whole pipeline, as an eval must pass before it is trusted."""

    def test_perfect_reader_with_full_history_scores_everything(self):
        arm = run("none", "oracle")
        self.assertEqual(arm["memory"][0], arm["memory"][1])
        self.assertEqual(rate(arm, "control"), 1.0)

    def test_null_model_fails_everything_except_abstention(self):
        arm = run("none", "null")
        for cat in CATEGORIES:
            self.assertEqual(rate(arm, cat), 1.0 if cat == "abstain" else 0.0, cat)

    def test_gullible_model_is_caught_by_the_poison_probes_only(self):
        arm = run("none", "gullible")
        self.assertEqual(rate(arm, "poison"), 0.0)
        self.assertEqual(arm["outcomes"].get("poisoned"), arm["by_category"]["poison"][1])
        self.assertEqual(rate(arm, "recall"), 1.0)

    def test_the_mechanism_is_wired_trimming_loses_evidence(self):
        full, trimmed = run("none", "oracle"), run("trim", "oracle")
        self.assertLess(trimmed["memory"][0], full["memory"][0])
        self.assertLess(trimmed["peak_prompt"], full["peak_prompt"])
        self.assertEqual(rate(trimmed, "control"), 1.0)                              # same-turn work is unaffected

    def test_trimming_makes_counts_wrong_rather_than_unknown(self):
        trimmed = run("trim", "oracle", turns=80, seeds=4, per_category=3, threshold=6000)
        self.assertLess(rate(trimmed, "count"), 1.0)
        self.assertGreater(trimmed["outcomes"].get("wrong", 0), 0)

    def test_trimming_fails_inventory_and_temporal_probes_at_long_distance(self):
        trimmed = run("trim", "oracle", turns=80, seeds=4, per_category=3, threshold=6000)
        for cat in ("inventory", "temporal"):
            rows = [r for r in trimmed["rows"] if r["category"] == cat]
            far = [r for r in rows if r["distance"] is not None and r["distance"] > 30]
            self.assertTrue(far, cat)
            self.assertLess(sum(r["outcome"] == "correct" for r in far), len(far), cat)
            self.assertLess(rate(trimmed, cat), 1.0, cat)

    def test_edit_compaction_loses_only_tool_result_facts(self):
        arm = run("edit", "oracle")
        for cat in ("recall", "inventory", "temporal"):
            self.assertEqual(rate(arm, cat), 1.0, cat)
        self.assertLess(rate(arm, "tool_recall"), 1.0)

    def test_summary_that_copies_every_fact_loses_nothing(self):
        self.assertEqual(run("summary", "oracle")["memory"][0], run("none", "oracle")["memory"][0])

    def test_memory_tool_arm_saves_before_compaction_and_reads_notes_back(self):
        plain, noted = run("trim", "oracle"), run("trim", "oracle", memory=True)
        self.assertLess(plain["memory"][0], plain["memory"][1])
        self.assertEqual(noted["memory"][0], noted["memory"][1])                     # a note-taker that saves everything
        self.assertGreater(noted["calls"], plain["calls"])                           # saving and reading cost calls

    def test_strategy_that_cannot_fit_its_threshold_is_an_outcome_not_a_crash(self):
        arm = run("edit", "oracle", memory=True, threshold=2500)
        self.assertGreater(arm["outcomes"].get("compaction_failed", 0), 0)

    def test_caching_makes_full_history_far_cheaper_than_uncached(self):
        arm = run("none", "oracle")
        self.assertLess(arm["cost"]["claude-opus-5-5"] * 3, arm["cost_uncached"]["claude-opus-5-5"])
        self.assertGreater(arm["cache_read_share"], 0.8)


class GateTests(unittest.TestCase):
    base = {"edit": {"survival": 0.90, "cost": 1.00, "control": 1.0}}

    def test_gate_passes_within_tolerance_and_on_improvement(self):
        self.assertEqual(compare(self.base, {"edit": {"survival": 0.89, "cost": 1.04, "control": 1.0}}, 0.02, 0.05), [])
        self.assertEqual(compare(self.base, {"edit": {"survival": 0.99, "cost": 0.50, "control": 1.0}}, 0.02, 0.05), [])

    def test_gate_fails_on_lost_evidence_higher_cost_or_missing_arm(self):
        self.assertEqual(len(compare(self.base, {"edit": {"survival": 0.80, "cost": 1.00, "control": 1.0}}, 0.02, 0.05)), 1)
        self.assertEqual(len(compare(self.base, {"edit": {"survival": 0.90, "cost": 1.20, "control": 0.9}}, 0.02, 0.05)), 2)
        self.assertEqual(len(compare(self.base, {}, 0.02, 0.05)), 1)


if __name__ == "__main__":
    unittest.main()
