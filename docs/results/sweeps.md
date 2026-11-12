# Offline sweeps

10 shifts of 120 turns, priced on claude-opus-5-5, dollars per shift. Perfect-reader mock, estimated tokens, modelled cache: compare rows and columns, do not budget on the figures.

## Pause between operator turns

Calls inside one turn's tool loop are 5 s apart. The cache follows Inspect's policy: 5-minute entries, switching to 1-hour entries (written at twice the input price) once a pause has outlived 5 minutes. Compaction threshold 30,000 tokens.

| pause between turns | none (full history) | trim, keep 50% | edit, keep 3 tool results | summary | full history, 5-minute cache only | full history, no cache |
|---|---|---|---|---|---|---|
| 10 s | 1.93 | 1.43 | 1.20 | 1.39 | 1.93 | 29.95 |
| 120 s | 1.93 | 1.43 | 1.20 | 1.39 | 1.93 | 29.95 |
| 280 s | 1.93 | 1.43 | 1.20 | 1.40 | 1.93 | 29.95 |
| 400 s | 2.17 | 1.80 | 1.48 | 1.83 | 24.67 | 29.95 |
| 15 min | 2.17 | 1.80 | 1.48 | 1.83 | 24.67 | 29.95 |
| 40 min | 2.17 | 1.80 | 1.48 | 1.85 | 24.67 | 29.95 |
| 67 min | 39.10 | 20.81 | 18.64 | 15.99 | 24.67 | 29.95 |

## Compaction threshold

Evidence survival and cost per shift, 10 s between turns.

| strategy | 15,000 tokens | 30,000 tokens | 60,000 tokens |
|---|---|---|---|
| trim, keep 50% | 32%, $1.13 | 53%, $1.43 | 78%, $1.80 |
| edit, keep 3 tool results | 87%, $1.14 | 93%, $1.20 | 96%, $1.55 |
| summary | live only, $1.34 | live only, $1.39 | live only, $1.78 |
