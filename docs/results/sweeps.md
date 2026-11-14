# Offline sweeps

10 shifts of 120 turns, priced on claude-opus-5-5, dollars per shift. Perfect-reader mock, estimated tokens, modelled cache: compare rows and columns, do not budget on the figures.

## Pause between operator turns

Calls inside one turn's tool loop are 5 s apart. The cache follows Inspect's policy: 5-minute entries, switching to 1-hour entries (written at twice the input price) once a pause has outlived 5 minutes. Compaction threshold 30,000 tokens.

| pause between turns | none (full history) | trim, keep 50% | edit, keep 3 tool results | summary | full history, 5-minute cache only | full history, no cache |
|---|---|---|---|---|---|---|
| 10 s | 1.21 | 1.06 | 0.89 | 0.99 | 1.21 | 18.31 |
| 120 s | 1.21 | 1.06 | 0.89 | 0.99 | 1.21 | 18.31 |
| 280 s | 1.21 | 1.06 | 0.89 | 0.99 | 1.21 | 18.31 |
| 400 s | 1.37 | 1.30 | 1.08 | 1.25 | 17.33 | 18.31 |
| 15 min | 1.37 | 1.30 | 1.08 | 1.25 | 17.33 | 18.31 |
| 40 min | 1.37 | 1.30 | 1.08 | 1.26 | 17.33 | 18.31 |
| 67 min | 27.55 | 19.46 | 17.09 | 15.02 | 17.33 | 18.31 |

## Compaction threshold

Evidence survival and cost per shift, 10 s between turns.

| strategy | 15,000 tokens | 30,000 tokens | 60,000 tokens |
|---|---|---|---|
| trim, keep 50% | 31%, $0.82 | 57%, $1.06 | 100%, $1.21 |
| edit, keep 3 tool results | 92%, $0.81 | 94%, $0.89 | 100%, $1.21 |
| summary | live only, $0.96 | live only, $0.99 | live only, $1.21 |
