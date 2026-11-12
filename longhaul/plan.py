"""Price a live sweep before spending anything.

    python -m longhaul.plan --turns 60 --seeds 3

Runs the planned sweep against the offline mock and prices the prompts it would send on each model.
The result is a FLOOR for the input side: a real model also writes thinking and longer answers (billed
as output), may take extra tool steps, and Claude's tokenizer tends to count more than the estimate.
"""
from __future__ import annotations

import argparse

from .cost import CARDS
from .sim import run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turns", type=int, default=60)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--threshold", type=int, default=30000)
    ap.add_argument("--per-category", type=int, default=2)
    ap.add_argument("--noise-chars", type=int, default=2400)
    ap.add_argument("--gap", type=float, default=10.0)
    args = ap.parse_args()
    arms = run("oracle", args.turns, args.seeds, args.threshold, args.noise_chars, args.per_category, args.gap)
    probes = arms[0]["memory"][1]
    print(f"Planned sweep: {len(arms)} strategies x {args.seeds} shifts x {args.turns} turns "
          f"({probes} memory probes per strategy, about {arms[0]['calls']:.0f} model calls per shift)\n")
    print("| model | " + " | ".join(a["label"] for a in arms) + " | whole sweep, floor |")
    print("|---|" + "---|" * (len(arms) + 1))
    for model in CARDS:
        per_arm = [a["cost"][model] * args.seeds for a in arms]
        print(f"| {model} | " + " | ".join(f"${c:.2f}" for c in per_arm) + f" | ${sum(per_arm):.2f} |")
    half = 100 / (probes ** 0.5) if probes else 0
    print(f"\nWith {probes} probes per strategy, a difference between two strategies smaller than about "
          f"{half:.0f} percentage points is within noise. More seeds narrow it.")


if __name__ == "__main__":
    main()
