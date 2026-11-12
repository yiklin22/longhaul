"""Regression gate: fail when a change moves what the strategies keep or what they cost.

    python -m longhaul.gate            # compare with baselines/offline.json, exit 1 on a regression
    python -m longhaul.gate --update   # accept the current numbers as the new baseline

The offline run is deterministic, so any difference comes from a code or dependency change (for example a
new Inspect release changing how a compaction strategy behaves). Tolerances exist so that an improvement
or a rounding-level change does not block a merge.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .sim import run

BASELINE = Path(__file__).resolve().parents[1] / "baselines" / "offline.json"
CONFIG = {"turns": 60, "seeds": 3, "threshold": 12000, "noise_chars": 2400, "per_category": 2, "gap": 10.0}
MODEL = "claude-opus-5-5"


def measure() -> dict:
    out = {}
    for arm in run("oracle", **CONFIG):
        k, n = arm["memory"]
        out[arm["label"]] = {"survival": round(k / n, 4), "cost": round(arm["cost"][MODEL], 4),
                             "control": round(arm["by_category"]["control"][0] / arm["by_category"]["control"][1], 4)}
    return out


def compare(baseline: dict, current: dict, survival_drop: float, cost_rise: float) -> list[str]:
    problems = []
    for label, base in baseline.items():
        now = current.get(label)
        if now is None:
            problems.append(f"{label}: missing from the current run")
            continue
        if now["survival"] < base["survival"] - survival_drop:
            problems.append(f"{label}: evidence survival fell {base['survival']:.0%} -> {now['survival']:.0%}")
        if now["control"] < base["control"]:
            problems.append(f"{label}: control accuracy fell {base['control']:.0%} -> {now['control']:.0%}")
        if now["cost"] > base["cost"] * (1 + cost_rise):
            problems.append(f"{label}: cost per shift rose ${base['cost']:.3f} -> ${now['cost']:.3f}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--survival-drop", type=float, default=0.02, help="allowed absolute fall in survival")
    ap.add_argument("--cost-rise", type=float, default=0.05, help="allowed relative rise in cost")
    args = ap.parse_args()
    current = measure()
    if args.update or not BASELINE.exists():
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps({"config": CONFIG, "model": MODEL, "arms": current}, indent=2) + "\n")
        print(f"baseline written: {BASELINE}")
        return
    problems = compare(json.loads(BASELINE.read_text())["arms"], current, args.survival_drop, args.cost_rise)
    for label, now in current.items():
        print(f"{label:28s} survival {now['survival']:.0%}  control {now['control']:.0%}  ${now['cost']:.3f}")
    if problems:
        print("\nREGRESSION\n" + "\n".join(f"- {p}" for p in problems))
        sys.exit(1)
    print("\ngate passed")


if __name__ == "__main__":
    main()
