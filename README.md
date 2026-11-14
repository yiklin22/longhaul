# longhaul

**Which context strategy keeps a long-running agent correct, and what does it actually cost once prompt caching is counted?**

Long agent runs outgrow their context, so every team picks a strategy: send everything, trim, clear old tool results, or summarise. Most comparisons price every input token at full rate, which is not what a cached agent loop pays. `longhaul` measures both sides on the same run: what the agent still remembers, and the bill with cache reads and writes priced separately.

It is built on [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai), the UK AI Security Institute's eval framework. The strategies under test are Inspect's own `CompactionTrim`, `CompactionEdit`, `CompactionSummary` and `CompactionNative`, not reimplementations, so the results describe what Inspect users actually run.

## Status

| Piece | State |
|---|---|
| Workload, grading, Inspect task, cost model, report, regression gate | Built, 46 tests passing offline, CI green |
| Offline results (below) | Real and reproducible: `python -m longhaul.sim` |
| Live model results | **Not run yet.** No API key was available. Commands are below; nothing in this README is a live-model number |

## Offline results

10 shifts of 120 turns, 400 memory probes per strategy, compaction threshold 30,000 tokens. Full table: [docs/results/offline.md](docs/results/offline.md).

| strategy | evidence survival (95% CI) | peak prompt tokens | $ / shift on Opus 5.5, cached | same, uncached |
|---|---|---|---|---|
| none (full history) | 100% (99-100) | 50,930 | 1.21 | 18.31 |
| trim, keep 50% | 57% (52-62) | 31,639 | 1.06 | 12.62 |
| edit, keep 3 tool results | 94% (92-96) | 31,272 | 0.89 | 11.35 |
| summary | needs a live run | 34,190 | 0.99 | 9.98 |
| trim + memory tool | needs a live run | 41,516 | 2.21 | 21.80 |
| edit + memory tool | needs a live run | 42,987 | 1.76 | 19.51 |

**What "evidence survival" means.** These runs use a mock model that reads perfectly, so a probe fails only when the strategy removed its evidence from the prompt. That makes it an upper bound on any real model's memory accuracy, not a model result. Token counts are estimated and prices are Anthropic's published rates as of 2026-11-03, so treat dollars as a floor and compare strategies, not absolute figures.

What the offline numbers already show:

1. **Caching outweighs the choice of strategy.** Full history costs $1.21 a shift with caching and $18.31 without. The best strategy saves 26% on top of caching; turning caching off costs about 15 times more.
2. **Clearing old tool results beat trimming on both axes here**: 94% against 57% survival, at $0.89 against $1.06.
3. **Trimming forgets by distance.** Survival is 100% for evidence up to 30 turns back and 24% beyond 60 turns.
4. **Edit compaction loses only what lived in tool results**: 45% on `tool_recall`, 100% on everything the operator said, including inventory and temporal probes.
5. **Trimming makes an agent wrong, not just forgetful.** On "how many" questions it was right 38% of the time and on "which accounts" questions 22%, and all 56 failures were confident short answers, not `UNKNOWN`: the agent cannot tell that part of the list is gone. On "what was it before the latest change" it was right 58% of the time; there all 17 failures were `UNKNOWN`, because trim had dropped at least two of the three values.
6. **A memory tool is not free.** Giving the agent Inspect's `memory()` tool, with the save-your-notes warning before each compaction, raises trim's cost from $1.06 to $2.21, more than sending full history ($1.21). The mock reads its notes before every question once it has saved any, which is stricter than the prompt asks, so part of that rise is the mock's own reading policy; the offline run does not separate it out. Whether the notes recover what trimming drops is a live question; the mock note-taker saves everything, so its score is not a finding.

### Pauses between turns change the answer

Same runs, re-priced as the operator's pause between turns grows ($ per shift, Opus 5.5). Full table: [docs/results/sweeps.md](docs/results/sweeps.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/pause-cost-dark.svg">
  <img alt="Line chart of modelled cost per shift against the pause between operator turns. Full history costs $1.21 up to a 4.7-minute pause, $1.37 up to 40 minutes, and $27.55 at 67 minutes, above the $18.31 no-cache cost. With only a 5-minute cache it jumps to $17.33 once pauses pass five minutes." src="docs/img/pause-cost-light.svg">
</picture>

| pause between turns | full history | edit | summary | full history, 5-minute cache only | no cache |
|---|---|---|---|---|---|
| up to 280 s | 1.21 | 0.89 | 0.99 | 1.21 | 18.31 |
| 400 s to 40 min | 1.37 | 1.08 | 1.25 to 1.26 | 17.33 | 18.31 |
| 67 min | 27.55 | 17.09 | 15.02 | 17.33 | 18.31 |

7. **A pause just over five minutes costs 14 times more on a plain 5-minute cache** ($1.21 to $17.33), because every turn rewrites the whole prompt. Inspect's switch to one-hour entries holds it to $1.37.
8. **Past an hour, caching full history costs more than not caching at all** ($27.55 against $18.31): every turn pays the one-hour write price, twice the input rate, and never reads it back. This is where summarising becomes the cheapest option.
9. **A lower compaction threshold buys little for edit and costs trim a lot.** From 60,000 to 15,000 tokens, edit drops from 100% to 92% survival and trim from 100% to 31%.

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
| `count` | how many accounts the operator gave a kind of fact for; needs every one |
| `inventory` | which accounts the operator gave a kind of fact for; graded as a set, order-free; a missing or extra account is `wrong` |
| `temporal` | a fact changed twice; asks for the value just before the latest change, so neither the first nor the current value passes |
| `control` | answer is in the same turn; needs no memory |

The cost model ([longhaul/cost.py](longhaul/cost.py)) replays the exact messages of every model call in an Inspect log through a prefix-cache simulation: breakpoints, minimum cacheable size, 20-block lookback, and the 5-minute and 1-hour lifetimes. It works on any Inspect agent log. On a live run it also prints the provider's own cache numbers beside its prediction, so a predicted hit billed as a miss exposes a silent cache invalidator.

## Run it

```bash
uv venv && uv pip install -e .
python -m unittest discover -s tests -t .       # 46 tests, no API key
python -m longhaul.sim                          # the offline table above, about a minute
python -m longhaul.sweep                        # pause and threshold sweeps, about three minutes
python -m longhaul.gate                         # regression gate against baselines/offline.json
python -m longhaul.chart                        # redraw the chart from the sweep table
```

Live, one strategy per run (needs `ANTHROPIC_API_KEY` and `uv pip install -e ".[live]"`):

```bash
inspect eval longhaul/longhaul --model anthropic/claude-opus-5-5 --log-dir logs \
  -T strategy=edit -T threshold=30000 -T turns=120 -T seeds=10 -T per_category=4
python -m longhaul.report logs --out docs/results/live.md
```

Strategies: `none`, `trim`, `edit`, `summary`, `native`, `auto`. Add `-T memory=true` to give the agent the memory tool.

**Price a sweep before running it:** `python -m longhaul.plan --turns 60 --seeds 3` prices the prompts the sweep would send. For that pilot (6 strategies, 3 shifts, 60 turns) the input-side floor is about $7.56 on Opus 5.5, $3.78 on Sonnet 5.5 and $0.30 on Haiku 5.5. Real runs cost more: output and thinking tokens are extra, and Claude's tokenizer tends to count more than the estimate. With 60 probes per strategy, that pilot only resolves differences larger than about 13 percentage points.

### LongMemEval, replayed

The synthetic shift gives exact grading. For results on a benchmark people already know, the same strategies run on [LongMemEval](https://github.com/xiaowu0162/LongMemEval) (get its data files from that repo; they are not bundled):

```bash
inspect eval longhaul/longmemeval --model anthropic/claude-opus-5-5 --model-role grader=<judge model> \
  -T data=longmemeval_s.json -T strategy=edit -T threshold=60000 -T limit=50 --log-dir logs-lme
python -m longhaul.cost logs-lme          # cache-aware cost of any Inspect logs
```

The chat history is replayed as real conversation turns, session by session, with the strategy running as it grows, and the question is asked in that conversation. The paper instead puts the whole history in one prompt, so these numbers are not comparable with its tables. Answers are graded with the paper's own judge prompts. The adapter is tested on a made-up file in the benchmark's format; it has not been run on the real data or a real model.

## Why the numbers can be trusted

- **Known-good and known-bad models run through the whole pipeline in CI.** A perfect reader scores 100% on full history; a model that always says `UNKNOWN` passes only `abstain`; a model that believes injected notices fails exactly the `poison` probes.
- **No answer is not a negative answer.** `abstained` and `no_answer` are separate outcomes, and overflow, truncation, refusal, step-limit and a strategy that cannot get under its threshold are recorded as themselves. Errored samples are left out, not scored as zero.
- **Deterministic grading** on a final `ANSWER:` line, or on the tool's received arguments. Listing two candidate values does not pass.
- **Both directions are covered.** Always answering fails `abstain`; always saying `UNKNOWN` fails the rest.
- **Intervals on every rate**, and every headline is recomputed from per-probe rows in the log.
- **A regression gate runs in CI.** The offline run is deterministic, so if a code change or a new Inspect release makes a strategy keep less evidence or cost more than the committed baseline, the build fails.

## Limits

- No live-model result exists yet, on the synthetic shift or on LongMemEval. How well a real model reads a 72K-token prompt, and how much a real summariser keeps, are the open questions this was built to answer.
- The cache model's breakpoints and lifetime follow Inspect's Anthropic provider as read from its source (v0.3.289). It has not been checked against live usage numbers.
- The workload is synthetic and fact-shaped. It tests counting, inventory ("which accounts have we given an escalation code") and one form of temporal ordering (the value before the latest change), but not open-ended inventory ("what have we worked on") or ordering across different facts.
- Current Claude models bind thinking blocks to the conversation that produced them. Inspect's Anthropic provider (v0.3.289) asks the API to drop a block whose history was edited instead of rejecting the request, and logs each drop. So trim, edit and summary should run on Claude 5.x through the first-party API, but lose reasoning each time they edit. The report counts those drops per strategy on a live run; none has been measured yet.

## Related work

- [nchapman/context-eval](https://github.com/nchapman/context-eval) compares compaction designs for coding agents and reports that inventory, supersession and counting are where they separate.
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval) and [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) are the established long-term-memory benchmarks; neither appeared in the [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) listing when checked on 2026-11-11.
- [t46/compactionbench](https://github.com/t46/compactionbench) and [chowdarymcs/agent-context-cost-benchmark](https://github.com/chowdarymcs/agent-context-cost-benchmark) study compaction and cost on local or mock models.

What is different here: the strategies are Inspect's shipped implementations, and cost is priced with cache reads and writes instead of a flat input rate.

## Roadmap

1. Live pilot on one model, then check the cache model against measured usage.
2. Run the memory-tool arms and native compaction live (both are wired; neither has met a real model).
3. Run the LongMemEval adapter on the real data, check the judge against a hand-labelled sample, then offer it upstream to `inspect_evals`.
4. Extend the regression gate to live runs, with tolerances set from run-to-run variance.

## Using it on a customer deployment

1. Measure their workload shape: turns per session, tokens per tool result, idle gaps between turns.
2. Set `turns`, `noise_chars` and `--gap` to match, and run the sweep on the model they use.
3. Agree the success metric up front, for example memory accuracy at or above a floor at the lowest cost per session.
4. Ship the winning strategy behind the cache check, so a later prompt change that breaks caching is caught by the bill prediction, not the invoice.

MIT licence.
