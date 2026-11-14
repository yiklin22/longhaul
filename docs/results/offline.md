# Offline results (oracle mock)

10 shifts of 120 turns, about 2400 characters of ticket text per routine turn, compaction threshold 30,000 tokens, 10 s between calls. Token counts are estimated (characters / 2.4, fitted to the offline token counter; Claude's tokenizer tends to count more, so treat dollar figures as a floor); prices are per shift.

**Read the accuracy column as evidence survival**: the share of probes whose evidence was still in the prompt, scored by a mock that reads perfectly. It is an upper bound for any real model, not a model result.

| strategy | evidence survival (95% CI) | n | peak prompt tokens | cache-read share | $ / shift, opus-5-5 | $ / shift, sonnet-5-5 | $ / shift, haiku-5-5 |
|---|---|---|---|---|---|---|---|
| none (full history) | 100% (99-100) | 400 | 50,930 | 99% | 1.212 (uncached 18.312) | 0.606 (uncached 9.156) | 0.053 (uncached 0.458) |
| trim, keep 50% | 57% (52-62) | 400 | 31,639 | 98% | 1.056 (uncached 12.615) | 0.528 (uncached 6.308) | 0.042 (uncached 0.315) |
| edit, keep 3 tool results | 94% (92-96) | 400 | 31,272 | 98% | 0.895 (uncached 11.355) | 0.447 (uncached 5.677) | 0.036 (uncached 0.284) |
| summary | needs a live run | 400 | 34,190 | 97% | 0.985 (uncached 9.976) | 0.493 (uncached 4.988) | 0.037 (uncached 0.249) |
| trim + memory tool | needs a live run | 400 | 41,516 | 96% | 2.209 (uncached 21.798) | 1.105 (uncached 10.899) | 0.081 (uncached 0.545) |
| edit + memory tool | needs a live run | 400 | 42,987 | 97% | 1.756 (uncached 19.514) | 0.878 (uncached 9.757) | 0.067 (uncached 0.488) |

### By category

| strategy | recall | tool_recall | update | multi_hop | abstain | poison | action | count | inventory | temporal | control |
|---|---|---|---|---|---|---|---|---|---|---|---|
| none (full history) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| trim, keep 50% | 62% (47-76) | 52% (37-67) | 78% (62-88) | 55% (40-69) | 100% (91-100) | 52% (37-67) | 50% (35-65) | 38% (24-53) | 22% (12-38) | 58% (42-71) | 100% (94-100) |
| edit, keep 3 tool results | 100% (91-100) | 45% (31-60) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (91-100) | 100% (94-100) |
| summary | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 100% (94-100) |
| trim + memory tool | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 100% (94-100) |
| edit + memory tool | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 100% (94-100) |

### What went wrong (memory probes)

| strategy | stale | poisoned | abstained | wrong | no_answer | other |
|---|---|---|---|---|---|---|
| none (full history) | 0 | 0 | 0 | 0 | 0 | 0 |
| trim, keep 50% | 0 | 0 | 117 | 56 | 0 | 0 |
| edit, keep 3 tool results | 0 | 0 | 22 | 0 | 0 | 0 |
| summary | 0 | 0 | 0 | 0 | 0 | 0 |
| trim + memory tool | 0 | 0 | 0 | 0 | 0 | 0 |
| edit + memory tool | 0 | 0 | 0 | 0 | 0 | 0 |

### By distance to the evidence

| strategy | <= 10 turns | 11-30 turns | 31-60 turns | > 60 turns |
|---|---|---|---|---|
| none (full history) | 100% (81-100) n=16 | 100% (93-100) n=48 | 100% (97-100) n=106 | 100% (98-100) n=190 |
| trim, keep 50% | 100% (81-100) n=16 | 100% (93-100) n=48 | 73% (63-80) n=106 | 24% (19-31) n=190 |
| edit, keep 3 tool results | 100% (81-100) n=16 | 96% (86-99) n=48 | 94% (88-97) n=106 | 93% (88-96) n=190 |
| summary | 100% (81-100) n=16 | 100% (93-100) n=48 | 100% (97-100) n=106 | 100% (98-100) n=190 |
| trim + memory tool | 100% (81-100) n=16 | 100% (93-100) n=48 | 100% (97-100) n=106 | 100% (98-100) n=190 |
| edit + memory tool | 100% (81-100) n=16 | 100% (93-100) n=48 | 100% (97-100) n=106 | 100% (98-100) n=190 |
