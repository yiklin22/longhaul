"""Regression gate: fail when a change moves what the strategies keep or what they cost.

    python -m longhaul.gate            # compare with baselines/offline.json, exit 1 on a regression
    python -m longhaul.gate --update   # accept the current numbers as the new baseline
    python -m longhaul.gate --live LOG_DIR            # compare live logs with baselines/live-<model>.json
    python -m longhaul.gate --live LOG_DIR --update   # accept a live run as that model's baseline

The offline run is deterministic, so any difference comes from a code or dependency change (for example a
new Inspect release changing how a compaction strategy behaves). Tolerances exist so that an improvement
or a rounding-level change does not block a merge.

A live run is not deterministic: its accuracy floor comes from sampling noise and its cost gets a stated
relative tolerance; see `live_limits`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cost import CARDS
from .report import arm_stats, wilson
from .sim import run

BASELINE = Path(__file__).resolve().parents[1] / "baselines" / "offline.json"
CONFIG = {"turns": 60, "seeds": 3, "threshold": 12000, "noise_chars": 2400, "per_category": 2, "gap": 10.0}
MODEL = "claude-opus-5-5"
LIVE_COST_RISE = 0.15   # allowed relative rise in measured cost per shift on a live run


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


def live_summary(arms: list[dict]) -> tuple[str, dict]:
    """Model name and per-strategy memory accuracy and measured cost per shift, from `report.arm_stats` dicts."""
    arms = [a for a in arms if a["shifts"]]
    models = {a["model"].split("/")[-1] for a in arms}
    if len(models) != 1:
        raise ValueError(f"expected logs from one model, found {sorted(models) or 'none'}")
    model = models.pop()
    if model not in CARDS:
        raise ValueError(f"no price card for {model} in cost.CARDS")
    out = {}
    for a in arms:
        if a["strategy"] in out:
            raise ValueError(f"two logs for strategy {a['strategy']}; keep one run per strategy in the directory")
        k, n = a["memory"]
        out[a["strategy"]] = {"correct": k, "probes": n, "cost": a["measured"]["cost"][model]}
    return model, out


def live_limits(arm: dict) -> dict:
    """The floor on memory accuracy and the ceiling on measured cost that a later run must stay within.

    With one baseline run there is no run-to-run variance yet, so the accuracy floor is the lower end of the
    95% Wilson interval on the baseline's own rate: the lowest true rate the baseline is consistent with. A
    later run below it is unlikely to be the same strategy drawing a bad sample. This was chosen over a
    two-proportion test because it gives one stored number per strategy that the comparison reads as is,
    it behaves at 0% and 100% where the normal approximation does not, and it reuses `report.wilson`. It
    ignores the new run's own noise; if the baseline rate were the true rate, a 48-probe run would fall below
    the floor about 2% of the time at the pilot's 33/48, and far less often near 100%. Cost has no sampling model, so it gets a stated relative tolerance.

    To use measured variance once there are repeated runs, change only this function (for example floor =
    mean minus two standard deviations across runs) and re-run with --update; `compare_live` reads only the
    stored floor and ceiling.
    """
    return {"floor": round(wilson(arm["correct"], arm["probes"])[0], 4),
            "cost_ceiling": round(arm["cost"] * (1 + LIVE_COST_RISE), 6)}


def live_baseline(model: str, current: dict) -> dict:
    arms = {s: {**a, "accuracy": round(a["correct"] / a["probes"], 4), "cost": round(a["cost"], 6), **live_limits(a)}
            for s, a in sorted(current.items())}
    return {"model": model, "cost_rise": LIVE_COST_RISE, "arms": arms}


def compare_live(baseline: dict, model: str, current: dict) -> list[str]:
    if model != baseline["model"]:
        raise ValueError(f"run is {model} but the baseline is {baseline['model']}; compare like with like")
    problems = []
    for strategy, base in baseline["arms"].items():
        now = current.get(strategy)
        if now is None:
            problems.append(f"{strategy}: missing from the current run")
            continue
        rate = now["correct"] / now["probes"] if now["probes"] else 0.0
        if rate < base["floor"]:
            problems.append(f"{strategy}: memory accuracy {rate:.0%} is below the baseline's floor {base['floor']:.0%} "
                            f"(baseline {base['correct']}/{base['probes']})")
        if now["cost"] > base["cost_ceiling"]:
            problems.append(f"{strategy}: measured cost per shift rose ${base['cost']:.4f} -> ${now['cost']:.4f}")
    return problems


def live_main(log_dir: str, update: bool) -> None:
    from inspect_ai.log import list_eval_logs, read_eval_log
    try:
        model, current = live_summary([arm_stats(read_eval_log(i), None) for i in list_eval_logs(log_dir)])
    except ValueError as e:
        sys.exit(f"refused: {e}")
    path = BASELINE.parent / f"live-{model}.json"
    if update:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(live_baseline(model, current), indent=2) + "\n")
        print(f"baseline written: {path}")
        return
    if not path.exists():
        sys.exit(f"refused: no live baseline for {model} ({path.name}); write one with --update")
    try:
        problems = compare_live(json.loads(path.read_text()), model, current)
    except ValueError as e:
        sys.exit(f"refused: {e}")
    for strategy, now in sorted(current.items()):
        print(f"{strategy:16s} memory {now['correct']}/{now['probes']}  measured ${now['cost']:.4f} per shift")
    if problems:
        print("\nREGRESSION\n" + "\n".join(f"- {p}" for p in problems))
        sys.exit(1)
    print("\nlive gate passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--live", metavar="LOG_DIR", help="gate a live run's Inspect logs instead of the offline run")
    ap.add_argument("--survival-drop", type=float, default=0.02, help="allowed absolute fall in survival")
    ap.add_argument("--cost-rise", type=float, default=0.05, help="allowed relative rise in cost")
    args = ap.parse_args()
    if args.live:
        return live_main(args.live, args.update)
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
