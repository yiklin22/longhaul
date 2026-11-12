# Offline results (oracle mock)

10 shifts of 120 turns, about 2400 characters of ticket text per routine turn, compaction threshold 30,000 tokens, 10 s between calls. Token counts are estimated (characters / 2.4, fitted to the offline token counter; Claude's tokenizer tends to count more, so treat dollar figures as a floor); prices are per shift.

**Read the accuracy column as evidence survival**: the share of probes whose evidence was still in the prompt, scored by a mock that reads perfectly. It is an upper bound for any real model, not a model result.

| strategy | evidence survival (95% CI) | n | peak prompt tokens | cache-read share | $ / shift, opus-5-5 | $ / shift, sonnet-5-5 | $ / shift, haiku-5-5 |
|---|---|---|---|---|---|---|---|
| none (full history) | 100% (99-100) | 280 | 76,013 | 99% | 1.930 (uncached 29.952) | 0.965 (uncached 14.976) | 0.085 (uncached 0.749) |
| trim, keep 50% | 53% (47-59) | 280 | 30,806 | 97% | 1.425 (uncached 15.317) | 0.713 (uncached 7.658) | 0.054 (uncached 0.383) |
| edit, keep 3 tool results | 93% (89-95) | 280 | 32,179 | 97% | 1.198 (uncached 13.992) | 0.599 (uncached 6.996) | 0.047 (uncached 0.350) |
| summary | needs a live run | 280 | 34,014 | 95% | 1.387 (uncached 11.892) | 0.694 (uncached 5.946) | 0.049 (uncached 0.297) |

### By category

| strategy | recall | tool_recall | update | multi_hop | abstain | poison | action | control |
|---|---|---|---|---|---|---|---|---|
| none (full history) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| trim, keep 50% | 60% (45-74) | 60% (45-74) | 60% (45-74) | 22% (12-38) | 100% (91-100) | 15% (7-29) | 55% (40-69) | 100% (94-100) |
| edit, keep 3 tool results | 100% (91-100) | 50% (35-65) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| summary | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 100% (94-100) |

### What went wrong (memory probes)

| strategy | stale | poisoned | abstained | wrong | no_answer | other |
|---|---|---|---|---|---|---|
| none (full history) | 0 | 0 | 0 | 0 | 0 | 0 |
| trim, keep 50% | 1 | 0 | 130 | 0 | 0 | 0 |
| edit, keep 3 tool results | 0 | 0 | 20 | 0 | 0 | 0 |
| summary | 0 | 0 | 0 | 0 | 0 | 0 |

### By distance to the evidence

| strategy | <= 10 turns | 11-30 turns | 31-60 turns | > 60 turns |
|---|---|---|---|---|
| none (full history) | 100% (81-100) n=16 | 100% (93-100) n=53 | 100% (95-100) n=72 | 100% (96-100) n=99 |
| trim, keep 50% | 100% (81-100) n=16 | 98% (90-100) n=53 | 35% (25-46) n=72 | 16% (10-25) n=99 |
| edit, keep 3 tool results | 100% (81-100) n=16 | 92% (82-97) n=53 | 92% (83-96) n=72 | 90% (82-94) n=99 |
| summary | 100% (81-100) n=16 | 100% (93-100) n=53 | 100% (95-100) n=72 | 100% (96-100) n=99 |
