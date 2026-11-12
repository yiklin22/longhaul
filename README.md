# longhaul

**Which context strategy keeps a long-running agent correct, and what does it actually cost once prompt caching is counted?**

Long agent runs outgrow their context, so every team picks a strategy: send everything, trim, clear old tool results, or summarise. Most comparisons price every input token at full rate, which is not what a cached agent loop pays. `longhaul` measures both sides on the same run: what the agent still remembers, and the bill with cache reads and writes priced separately.

It is built on [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai), the UK AI Security Institute's eval framework. The strategies under test are Inspect's own `CompactionTrim`, `CompactionEdit`, `CompactionSummary` and `CompactionNative`, not reimplementations, so the results describe what Inspect users actually run.

## Status

| Piece | State |
|---|---|
| Workload, grading, Inspect task, cost model, report | Built, 24 tests passing offline |
| Offline results (below) | Real and reproducible: `python -m longhaul.sim` |
| Live model results | **Not run yet.** No API key was available. Commands are below; nothing in this README is a live-model number |

## Offline results

10 shifts of 120 turns, 280 memory probes per strategy, compaction threshold 30,000 tokens. Full table: [docs/results/offline.md](docs/results/offline.md).

| strategy | evidence survival (95% CI) | peak prompt tokens | $ / shift on Opus 5.5, cached | same, uncached |
|---|---|---|---|---|
| none (full history) | 100% (99-100) | 76,013 | 1.93 | 29.95 |
| trim, keep 50% | 53% (47-59) | 30,806 | 1.43 | 15.32 |
| edit, keep 3 tool results | 93% (89-95) | 32,179 | 1.20 | 13.99 |
| summary | needs a live run | 34,014 | 1.39 | 11.89 |

**What "evidence survival" means.** These runs use a mock model that reads perfectly, so a probe fails only when the strategy removed its evidence from the prompt. That makes it an upper bound on any real model's memory accuracy, not a model result. Token counts are estimated and prices are Anthropic's published rates as of 2026-11-03, so treat dollars as a floor and compare strategies, not absolute figures.

What the offline numbers already show:

1. **Caching outweighs the choice of strategy.** Full history costs $1.93 a shift with caching and $29.95 without. The best strategy saves 38% on top of caching; turning caching off costs 15 times more.
2. **Clearing old tool results beat trimming on both axes here**: 93% against 53% survival, at $1.20 against $1.43.
3. **Trimming forgets by distance.** Survival is 98% for evidence up to 30 turns back and 16% beyond 60 turns.
4. **Edit compaction loses only what lived in tool results**: 50% on `tool_recall`, 100% on everything the operator said.
5. **Trimming can make an agent wrong, not just forgetful.** Inspect's trim pins the first user message. In one probe of 280 the original value survived there while the later correction was trimmed, so the retired value was the only one left to read.

## How it works

One sample is one long support shift. The operator states account facts, changes some later, and asks for them many turns on, between routine ticket lookups that supply the token load. Everything is synthetic and seeded.

| Probe | Tests |
|---|---|
| `recall`, `tool_recall` | a fact the operator stated, or one seen only in a tool result |
| `update` | the latest value wins; answering the old one is scored `stale` |
| `multi_hop` | two facts from different turns |
| `abstain` | never stated; the right answer is `UNKNOWN` |
| `poison` | a tool result claims another value; answering it is scored `poisoned` |
| `action` | the value must reach a tool call; graded on what the tool received |
| `control` | answer is in the same turn; needs no memory |

The cost model ([longhaul/cost.py](longhaul/cost.py)) replays the exact messages of every model call in an Inspect log through a prefix-cache simulation: breakpoints, minimum cacheable size, 20-block lookback, 5-minute lifetime. It works on any Inspect agent log. On a live run it also prints the provider's own cache numbers beside its prediction, so a predicted hit billed as a miss exposes a silent cache invalidator.

## Run it

```bash
uv venv && uv pip install -e .
python -m unittest discover -s tests -t .       # 24 tests, no API key
python -m longhaul.sim                          # the offline table above, about a minute
```

Live, one strategy per run (needs `ANTHROPIC_API_KEY` and `uv pip install -e ".[live]"`):

```bash
inspect eval longhaul/longhaul --model anthropic/claude-opus-5-5 --log-dir logs \
  -T strategy=edit -T threshold=30000 -T turns=120 -T seeds=10 -T per_category=4
python -m longhaul.report logs --out docs/results/live.md
```

Strategies: `none`, `trim`, `edit`, `summary`, `native`, `auto`. **Cost before you run:** the offline table is a floor for input cost per shift; multiply by seeds and strategies, and add output and thinking tokens. A first pilot of 3 seeds at 60 turns is a small fraction of the full sweep.

## Why the numbers can be trusted

- **Known-good and known-bad models run through the whole pipeline in CI.** A perfect reader scores 100% on full history; a model that always says `UNKNOWN` passes only `abstain`; a model that believes injected notices fails exactly the `poison` probes.
- **No answer is not a negative answer.** `abstained` and `no_answer` are separate outcomes, and overflow, truncation, refusal and step-limit are recorded as themselves. Errored samples are left out, not scored as zero.
- **Deterministic grading** on a final `ANSWER:` line, or on the tool's received arguments. Listing two candidate values does not pass.
- **Both directions are covered.** Always answering fails `abstain`; always saying `UNKNOWN` fails the rest.
- **Intervals on every rate**, and every headline is recomputed from per-probe rows in the log.

## Limits

- No live-model result exists yet. How well a real model reads a 76K-token prompt, and how much a real summariser keeps, are the open questions this was built to answer.
- The cache model's breakpoint placement is an assumption until checked against live usage numbers.
- The workload is synthetic and fact-shaped. It does not test counting, inventory ("what have we worked on") or temporal ordering.
- Current Claude models bind thinking blocks to the conversation that produced them, so client-side history edits (trim, edit, summary) may be rejected or lose reasoning. Whether Inspect's strategies handle this on Claude 5.x models is untested here.

## Related work

- [nchapman/context-eval](https://github.com/nchapman/context-eval) compares compaction designs for coding agents and reports that inventory, supersession and counting are where they separate.
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval) and [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) are the established long-term-memory benchmarks; neither is in [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) yet.
- [t46/compactionbench](https://github.com/t46/compactionbench) and [chowdarymcs/agent-context-cost-benchmark](https://github.com/chowdarymcs/agent-context-cost-benchmark) study compaction and cost on local or mock models.

What is different here: the strategies are Inspect's shipped implementations, and cost is priced with cache reads and writes instead of a flat input rate.

## Roadmap

1. Live pilot on one model, then check the cache model against measured usage.
2. Memory-tool arms (`memory=True`) and native compaction.
3. A LongMemEval adapter for external validity, offered upstream to `inspect_evals`.
4. Inventory, counting and temporal probes.
5. An eval gate: fail CI when a strategy's accuracy or cost moves past a threshold.

## Using it on a customer deployment

1. Measure their workload shape: turns per session, tokens per tool result, idle gaps between turns.
2. Set `turns`, `noise_chars` and `--gap` to match, and run the sweep on the model they use.
3. Agree the success metric up front, for example memory accuracy at or above a floor at the lowest cost per session.
4. Ship the winning strategy behind the cache check, so a later prompt change that breaks caching is caught by the bill prediction, not the invoice.

MIT licence.
