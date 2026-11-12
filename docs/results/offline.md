# Offline results (oracle mock)

10 shifts of 120 turns, about 2400 characters of ticket text per routine turn, compaction threshold 30,000 tokens, 10 s between calls. Token counts are estimated (characters / 2.4, fitted to the offline token counter; Claude's tokenizer tends to count more, so treat dollar figures as a floor); prices are per shift.

**Read the accuracy column as evidence survival**: the share of probes whose evidence was still in the prompt, scored by a mock that reads perfectly. It is an upper bound for any real model, not a model result.

| strategy | evidence survival (95% CI) | n | peak prompt tokens | cache-read share | $ / shift, opus-5-5 | $ / shift, sonnet-5-5 | $ / shift, haiku-5-5 |
|---|---|---|---|---|---|---|---|
| none (full history) | 100% (99-100) | 320 | 71,884 | 99% | 1.837 (uncached 28.562) | 0.919 (uncached 14.281) | 0.081 (uncached 0.714) |
| trim, keep 50% | 48% (42-53) | 320 | 30,650 | 97% | 1.347 (uncached 14.751) | 0.674 (uncached 7.375) | 0.051 (uncached 0.369) |
| edit, keep 3 tool results | 94% (91-96) | 320 | 32,212 | 97% | 1.143 (uncached 13.347) | 0.572 (uncached 6.673) | 0.045 (uncached 0.334) |
| summary | needs a live run | 320 | 34,059 | 95% | 1.341 (uncached 11.412) | 0.671 (uncached 5.706) | 0.047 (uncached 0.285) |

### By category

| strategy | recall | tool_recall | update | multi_hop | abstain | poison | action | count | control |
|---|---|---|---|---|---|---|---|---|---|
| none (full history) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| trim, keep 50% | 60% (45-74) | 60% (45-74) | 62% (47-76) | 22% (12-38) | 100% (91-100) | 15% (7-29) | 55% (40-69) | 5% (1-17) | 100% (94-100) |
| edit, keep 3 tool results | 100% (91-100) | 50% (35-65) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| summary | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 100% (94-100) |

### What went wrong (memory probes)

| strategy | stale | poisoned | abstained | wrong | no_answer | other |
|---|---|---|---|---|---|---|
| none (full history) | 0 | 0 | 0 | 0 | 0 | 0 |
| trim, keep 50% | 1 | 0 | 129 | 38 | 0 | 0 |
| edit, keep 3 tool results | 0 | 0 | 20 | 0 | 0 | 0 |
| summary | 0 | 0 | 0 | 0 | 0 | 0 |

### By distance to the evidence

| strategy | <= 10 turns | 11-30 turns | 31-60 turns | > 60 turns |
|---|---|---|---|---|
| none (full history) | 100% (81-100) n=16 | 100% (93-100) n=54 | 100% (95-100) n=75 | 100% (97-100) n=134 |
| trim, keep 50% | 100% (81-100) n=16 | 98% (90-100) n=54 | 33% (24-45) n=75 | 13% (8-19) n=134 |
| edit, keep 3 tool results | 100% (81-100) n=16 | 93% (82-97) n=54 | 92% (84-96) n=75 | 93% (87-96) n=134 |
| summary | 100% (81-100) n=16 | 100% (93-100) n=54 | 100% (95-100) n=75 | 100% (97-100) n=134 |
