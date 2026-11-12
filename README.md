# longhaul

**Which context strategy keeps a long-running agent correct, and what does it actually cost once prompt caching is counted?**

Long agent runs outgrow their context, so every team picks a strategy: send everything, trim, clear old tool results, or summarise. Most comparisons price every input token at full rate, which is not what a cached agent loop pays. `longhaul` measures both sides on the same run: what the agent still remembers, and the bill with cache reads and writes priced separately.

It is built on [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai), the UK AI Security Institute's eval framework. The strategies under test are Inspect's own `CompactionTrim`, `CompactionEdit`, `CompactionSummary` and `CompactionNative`, not reimplementations, so the results describe what Inspect users actually run.

## Status

| Piece | State |
|---|---|
| Workload, grading, Inspect task, cost model, report, regression gate | Built, 31 tests passing offline, CI green |
| Offline results (below) | Real and reproducible: `python -m longhaul.sim` |
| Live model results | **Not run yet.** No API key was available. Commands are below; nothing in this README is a live-model number |

## Offline results

10 shifts of 120 turns, 320 memory probes per strategy, compaction threshold 30,000 tokens. Full table: [docs/results/offline.md](docs/results/offline.md).

| strategy | evidence survival (95% CI) | peak prompt tokens | $ / shift on Opus 5.5, cached | same, uncached |
|---|---|---|---|---|
| none (full history) | 100% (99-100) | 71,884 | 1.84 | 28.56 |
| trim, keep 50% | 48% (42-53) | 30,650 | 1.35 | 14.75 |
| edit, keep 3 tool results | 94% (91-96) | 32,212 | 1.14 | 13.35 |
| summary | needs a live run | 34,059 | 1.34 | 11.41 |

**What "evidence survival" means.** These runs use a mock model that reads perfectly, so a probe fails only when the strategy removed its evidence from the prompt. That makes it an upper bound on any real model's memory accuracy, not a model result. Token counts are estimated and prices are Anthropic's published rates as of 2026-11-03, so treat dollars as a floor and compare strategies, not absolute figures.

What the offline numbers already show:

1. **Caching outweighs the choice of strategy.** Full history costs $1.84 a shift with caching and $28.56 without. The best strategy saves 38% on top of caching; turning caching off costs about 15 times more.
2. **Clearing old tool results beat trimming on both axes here**: 94% against 48% survival, at $1.14 against $1.35.
3. **Trimming forgets by distance.** Survival is 98% or better for evidence up to 30 turns back and 13% beyond 60 turns.
4. **Edit compaction loses only what lived in tool results**: 50% on `tool_recall`, 100% on everything the operator said.
5. **Trimming makes an agent wrong, not just forgetful.** On "how many" questions it was right 5% of the time, and the 38 failures were confident undercounts, not `UNKNOWN`: the agent cannot tell that part of the list is gone. Inspect's trim also pins the first user message, so in one probe the original value survived there while its later correction was trimmed.

### Pauses between turns change the answer

Same runs, re-priced as the operator's pause between turns grows ($ per shift, Opus 5.5). Full table: [docs/results/sweeps.md](docs/results/sweeps.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/pause-cost-dark.svg">
  <img alt="Line chart of modelled cost per shift against the pause between operator turns. Full history costs $1.84 up to a 4.7-minute pause, $2.06 up to 40 minutes, and $38.60 at 67 minutes, above the $28.56 no-cache cost. With only a 5-minute cache it jumps to $24.33 once pauses pass five minutes." src="docs/img/pause-cost-light.svg">
</picture>

| pause between turns | full history | edit | summary | full history, 5-minute cache only | no cache |
|---|---|---|---|---|---|
| up to 280 s | 1.84 | 1.14 | 1.34 to 1.35 | 1.84 | 28.56 |
| 400 s to 40 min | 2.06 | 1.41 | 1.77 to 1.79 | 24.33 | 28.56 |
| 67 min | 38.60 | 18.17 | 15.53 | 24.33 | 28.56 |

6. **A pause just over five minutes costs 13 times more on a plain 5-minute cache** ($1.84 to $24.33), because every turn rewrites the whole prompt. Inspect's switch to one-hour entries holds it to $2.06.
7. **Past an hour, caching full history costs more than not caching at all** ($38.60 against $28.56): every turn pays the one-hour write price, twice the input rate, and never reads it back. This is where summarising becomes the cheapest option.
8. **A lower compaction threshold buys little for edit and costs trim a lot.** From 60,000 to 15,000 tokens, edit drops from 97% to 89% survival and trim from 71% to 30%.

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
| `control` | answer is in the same turn; needs no memory |

The cost model ([longhaul/cost.py](longhaul/cost.py)) replays the exact messages of every model call in an Inspect log through a prefix-cache simulation: breakpoints, minimum cacheable size, 20-block lookback, and the 5-minute and 1-hour lifetimes. It works on any Inspect agent log. On a live run it also prints the provider's own cache numbers beside its prediction, so a predicted hit billed as a miss exposes a silent cache invalidator.

## Run it

```bash
uv venv && uv pip install -e .
python -m unittest discover -s tests -t .       # 31 tests, no API key
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

Strategies: `none`, `trim`, `edit`, `summary`, `native`, `auto`.

**Price a sweep before running it:** `python -m longhaul.plan --turns 60 --seeds 3` prices the prompts the sweep would send. For that pilot (4 strategies, 3 shifts, 60 turns) the input-side floor is about $7.01 on Opus 5.5, $3.50 on Sonnet 5.5 and $0.27 on Haiku 5.5. Real runs cost more: output and thinking tokens are extra, and Claude's tokenizer tends to count more than the estimate. With 48 probes per strategy, that pilot only resolves differences larger than about 14 percentage points.

## Why the numbers can be trusted

- **Known-good and known-bad models run through the whole pipeline in CI.** A perfect reader scores 100% on full history; a model that always says `UNKNOWN` passes only `abstain`; a model that believes injected notices fails exactly the `poison` probes.
- **No answer is not a negative answer.** `abstained` and `no_answer` are separate outcomes, and overflow, truncation, refusal and step-limit are recorded as themselves. Errored samples are left out, not scored as zero.
- **Deterministic grading** on a final `ANSWER:` line, or on the tool's received arguments. Listing two candidate values does not pass.
- **Both directions are covered.** Always answering fails `abstain`; always saying `UNKNOWN` fails the rest.
- **Intervals on every rate**, and every headline is recomputed from per-probe rows in the log.
- **A regression gate runs in CI.** The offline run is deterministic, so if a code change or a new Inspect release makes a strategy keep less evidence or cost more than the committed baseline, the build fails.

## Limits

- No live-model result exists yet. How well a real model reads a 76K-token prompt, and how much a real summariser keeps, are the open questions this was built to answer.
- The cache model's breakpoints and lifetime follow Inspect's Anthropic provider as read from its source (v0.3.289). It has not been checked against live usage numbers.
- The workload is synthetic and fact-shaped. It tests counting, but not inventory ("what have we worked on") or temporal ordering.
- Current Claude models bind thinking blocks to the conversation that produced them. Inspect's Anthropic provider (v0.3.289) asks the API to drop a block whose history was edited instead of rejecting the request, and logs each drop. So trim, edit and summary should run on Claude 5.x through the first-party API, but lose reasoning each time they edit. The report counts those drops per strategy on a live run; none has been measured yet.

## Related work

- [nchapman/context-eval](https://github.com/nchapman/context-eval) compares compaction designs for coding agents and reports that inventory, supersession and counting are where they separate.
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval) and [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) are the established long-term-memory benchmarks; neither is in [inspect_evals](https://github.com/UKGovernmentBEIS/inspect_evals) yet.
- [t46/compactionbench](https://github.com/t46/compactionbench) and [chowdarymcs/agent-context-cost-benchmark](https://github.com/chowdarymcs/agent-context-cost-benchmark) study compaction and cost on local or mock models.

What is different here: the strategies are Inspect's shipped implementations, and cost is priced with cache reads and writes instead of a flat input rate.

## Roadmap

1. Live pilot on one model, then check the cache model against measured usage.
2. Memory-tool arms (`memory=True`) and native compaction.
3. A LongMemEval adapter for external validity, offered upstream to `inspect_evals`.
4. Inventory and temporal probes.
5. Extend the regression gate to live runs, with tolerances set from run-to-run variance.

## Using it on a customer deployment

1. Measure their workload shape: turns per session, tokens per tool result, idle gaps between turns.
2. Set `turns`, `noise_chars` and `--gap` to match, and run the sweep on the model they use.
3. Agree the success metric up front, for example memory accuracy at or above a floor at the lowest cost per session.
4. Ship the winning strategy behind the cache check, so a later prompt change that breaks caching is caught by the bill prediction, not the invoice.

MIT licence.
