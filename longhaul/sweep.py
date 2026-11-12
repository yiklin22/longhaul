"""Offline sweeps over the two settings a deployment actually chooses: how long the operator pauses
between turns, and where compaction triggers.

    python -m longhaul.sweep --out docs/results/sweeps.md

Same caveats as `longhaul.sim`: a perfect-reader mock, estimated tokens, modelled cache.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.model import get_model

from .oracle import make_mock
from .report import arm_stats, pct
from .sim import ARMS as ALL_ARMS
from .task import REGISTRY, longhaul

ARMS = ALL_ARMS[:4]            # the memory-tool arms are priced in the main table only
GAPS = [10, 120, 280, 400, 900, 2400, 4000]
THRESHOLDS = [15000, 30000, 60000]
MODEL = "claude-opus-5-5"


def run_log(tmp: str, turns: int, seeds: int, threshold: int, params: dict):
    task = longhaul(threshold=threshold, turns=turns, seeds=seeds, per_category=4, **params)
    log = inspect_eval(task, model=get_model("mockllm/model", custom_outputs=make_mock("oracle", REGISTRY)),
                       log_dir=tmp, display="none")[0]
    if log.status != "success":
        raise RuntimeError(f"{params}: {log.status} {log.error}")
    return log


def gap_table(logs: dict[str, object]) -> str:
    """Cost per shift as the pause between operator turns grows. One run per strategy, re-priced per gap."""
    head = "| pause between turns | " + " | ".join(logs) + " | full history, 5-minute cache only | full history, no cache |"
    lines = [head, "|---|" + "---|" * (len(logs) + 2)]
    for gap in GAPS:
        cells = [f"{arm_stats(log, gap)['cost'][MODEL]:.2f}" for log in logs.values()]
        full = next(iter(logs.values()))
        plain = arm_stats(full, gap, escalate=False)
        label = f"{gap} s" if gap < 600 else f"{gap / 60:.0f} min"
        lines.append(f"| {label} | " + " | ".join(cells) +
                     f" | {plain['cost'][MODEL]:.2f} | {plain['cost_uncached'][MODEL]:.2f} |")
    return "\n".join(lines)


def threshold_table(tmp: str, turns: int, seeds: int) -> str:
    """Evidence survival and cost per shift at each compaction threshold."""
    lines = ["| strategy | " + " | ".join(f"{t:,} tokens" for t in THRESHOLDS) + " |", "|---|" + "---|" * len(THRESHOLDS)]
    for label, params in ARMS[1:]:
        cells = []
        for threshold in THRESHOLDS:
            arm = arm_stats(run_log(tmp, turns, seeds, threshold, params), 10.0)
            survival = "live only" if params["strategy"] == "summary" else pct(*arm["memory"]).split(" ")[0]
            cells.append(f"{survival}, ${arm['cost'][MODEL]:.2f}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turns", type=int, default=120)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--out")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="longhaul-") as tmp:
        logs = {label: run_log(tmp, args.turns, args.seeds, 30000, params) for label, params in ARMS}
        gaps = gap_table(logs)
        thresholds = threshold_table(tmp, args.turns, args.seeds)
    text = (f"# Offline sweeps\n\n{args.seeds} shifts of {args.turns} turns, priced on {MODEL}, dollars per shift. "
            "Perfect-reader mock, estimated tokens, modelled cache: compare rows and columns, do not budget on the figures.\n\n"
            "## Pause between operator turns\n\n"
            "Calls inside one turn's tool loop are 5 s apart. The cache follows Inspect's policy: 5-minute entries, "
            "switching to 1-hour entries (written at twice the input price) once a pause has outlived 5 minutes. "
            "Compaction threshold 30,000 tokens.\n\n" + gaps +
            "\n\n## Compaction threshold\n\nEvidence survival and cost per shift, 10 s between turns.\n\n" + thresholds + "\n")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
