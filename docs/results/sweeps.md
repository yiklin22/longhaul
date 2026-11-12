# Offline sweeps

10 shifts of 120 turns, priced on claude-opus-5-5, dollars per shift. Perfect-reader mock, estimated tokens, modelled cache: compare rows and columns, do not budget on the figures.

## Pause between operator turns

Calls inside one turn's tool loop are 5 s apart. The cache follows Inspect's policy: 5-minute entries, switching to 1-hour entries (written at twice the input price) once a pause has outlived 5 minutes. Compaction threshold 30,000 tokens.

| pause between turns | none (full history) | trim, keep 50% | edit, keep 3 tool results | summary | full history, 5-minute cache only | full history, no cache |
|---|---|---|---|---|---|---|
| 10 s | 1.84 | 1.35 | 1.14 | 1.34 | 1.84 | 28.56 |
| 120 s | 1.84 | 1.35 | 1.14 | 1.34 | 1.84 | 28.56 |
| 280 s | 1.84 | 1.35 | 1.14 | 1.35 | 1.84 | 28.56 |
| 400 s | 2.06 | 1.70 | 1.41 | 1.77 | 24.33 | 28.56 |
| 15 min | 2.06 | 1.70 | 1.41 | 1.77 | 24.33 | 28.56 |
| 40 min | 2.06 | 1.70 | 1.41 | 1.79 | 24.33 | 28.56 |
| 67 min | 38.60 | 20.43 | 18.17 | 15.53 | 24.33 | 28.56 |

## Compaction threshold

Evidence survival and cost per shift, 10 s between turns.

| strategy | 15,000 tokens | 30,000 tokens | 60,000 tokens |
|---|---|---|---|
| trim, keep 50% | 30%, $1.07 | 48%, $1.35 | 71%, $1.74 |
| edit, keep 3 tool results | 89%, $1.08 | 94%, $1.14 | 97%, $1.50 |
| summary | live only, $1.31 | live only, $1.34 | live only, $1.74 |
