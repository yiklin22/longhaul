"""Turn Inspect logs from longhaul runs into one comparison table.

    python -m longhaul.report logs/ --out docs/results/live.md
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log, resolve_sample_attachments

from .cost import CARDS, sample_calls, summarise
from .scenario import CATEGORIES

MEMORY = [c for c in CATEGORIES if c != "control"]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k successes in n trials."""
    if n == 0:
        return (0.0, 0.0)
    p, d = k / n, 1 + z * z / n
    centre, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def arm_stats(log, gap_s: float | None, chars_per_token: float = 2.4, escalate: bool = True) -> dict:
    """Pooled outcomes and per-shift cost for one log (one strategy). Recomputed from raw rows."""
    rows, modelled, uncached, measured = [], [], [], []
    for s in log.samples or []:
        score = (s.scores or {}).get("shift_scorer")
        if score is None:                      # errored sample: not a model failure, so not scored
            continue
        rows += score.metadata["rows"]
        # Inspect stores long message content once and references it; the cost model needs the real text.
        calls = sample_calls(resolve_sample_attachments(s, "full"), chars_per_token, gap_s, escalate=escalate)
        modelled.append(summarise(calls["modelled"]))
        uncached.append(summarise(calls["uncached"]))
        if calls["measured"]:
            measured.append(summarise(calls["measured"]))

    def acc(cats) -> tuple[int, int]:
        sel = [r for r in rows if r["category"] in cats]
        return sum(r["outcome"] == "correct" for r in sel), len(sel)

    def mean(items, key) -> float:
        return sum(key(i) for i in items) / len(items) if items else 0.0

    outcomes: dict[str, int] = {}
    for r in rows:
        if r["category"] != "control":
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "strategy": log.eval.metadata.get("strategy", log.eval.task) if log.eval.metadata else log.eval.task,
        "threshold": (log.eval.metadata or {}).get("threshold"),
        "model": log.eval.model,
        "shifts": len(modelled),
        "errors": len(log.samples or []) - len(modelled),
        "memory": acc(MEMORY),
        "by_category": {c: acc([c]) for c in CATEGORIES},
        "outcomes": outcomes,
        "rows": rows,
        "peak_prompt": mean(modelled, lambda m: m["peak_prompt"]),
        "calls": mean(modelled, lambda m: m["calls"]),
        "cache_read_share": mean(modelled, lambda m: m["cache_read_share"]),
        "cost": {c: mean(modelled, lambda m: m["cost"][c]) for c in CARDS},
        "cost_uncached": {c: mean(uncached, lambda m: m["cost"][c]) for c in CARDS},
        "measured": ({"cache_read_share": mean(measured, lambda m: m["cache_read_share"]),
                      "cost": {c: mean(measured, lambda m: m["cost"][c]) for c in CARDS}} if measured else None),
    }


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({100 * lo:.0f}-{100 * hi:.0f})"


def distance_table(arms: list[dict], edges=(10, 30, 60)) -> str:
    """Accuracy by how many turns back the evidence was: the forgetting curve."""
    labels = [f"<= {edges[0]}"] + [f"{a + 1}-{b}" for a, b in zip(edges, edges[1:])] + [f"> {edges[-1]}"]
    out = ["| strategy | " + " | ".join(f"{label} turns" for label in labels) + " |", "|---|" + "---|" * len(labels)]
    for arm in arms:
        cells = []
        for i in range(len(labels)):
            lo = -1 if i == 0 else edges[i - 1]
            hi = edges[i] if i < len(edges) else 10 ** 9
            sel = [r for r in arm["rows"] if r["distance"] is not None and r["category"] not in ("control", "abstain")
                   and lo < r["distance"] <= hi]
            cells.append(pct(sum(r["outcome"] == "correct" for r in sel), len(sel)) + f" n={len(sel)}")
        out.append(f"| {arm['label']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def render(arms: list[dict], accuracy_label: str, cost_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")) -> str:
    for a in arms:
        a.setdefault("label", a["strategy"])
    head = (f"| strategy | {accuracy_label} (95% CI) | n | peak prompt tokens | cache-read share | "
            + " | ".join(f"$ / shift, {m.replace('claude-', '')}" for m in cost_models) + " |")
    lines = [head, "|---|---|---|---|---|" + "---|" * len(cost_models)]
    for a in arms:
        k, n = a["memory"]
        lines.append(f"| {a['label']} | {a.get('accuracy_override') or pct(k, n)} | {n} | {a['peak_prompt']:,.0f} | "
                     f"{100 * a['cache_read_share']:.0f}% | " +
                     " | ".join(f"{a['cost'][m]:.3f} (uncached {a['cost_uncached'][m]:.3f})" for m in cost_models) + " |")
    cats = ["| strategy | " + " | ".join(CATEGORIES) + " |", "|---|" + "---|" * len(CATEGORIES)]
    for a in arms:
        cats.append(f"| {a['label']} | " + " | ".join(
            (a.get("accuracy_override") and c != "control" and "n/a") or pct(*a["by_category"][c]) for c in CATEGORIES) + " |")
    fails = ["| strategy | " + " | ".join(["stale", "poisoned", "abstained", "wrong", "no_answer", "other"]) + " |", "|---|---|---|---|---|---|---|"]
    for a in arms:
        o = a["outcomes"]
        known = ("correct", "stale", "poisoned", "abstained", "wrong", "no_answer")
        fails.append(f"| {a['label']} | " + " | ".join(str(o.get(x, 0)) for x in known[1:]) +
                     f" | {sum(v for x, v in o.items() if x not in known)} |")
    parts = ["\n".join(lines), "### By category\n\n" + "\n".join(cats), "### What went wrong (memory probes)\n\n" + "\n".join(fails),
             "### By distance to the evidence\n\n" + distance_table(arms)]
    measured = [a for a in arms if a["measured"]]
    if measured:
        m = ["| strategy | modelled cache-read share | measured | modelled $ (opus-5-5) | measured $ |", "|---|---|---|---|---|"]
        for a in measured:
            m.append(f"| {a['label']} | {100 * a['cache_read_share']:.0f}% | {100 * a['measured']['cache_read_share']:.0f}% | "
                     f"{a['cost']['claude-opus-5-5']:.3f} | {a['measured']['cost']['claude-opus-5-5']:.3f} |")
        parts.append("### Cache model against the provider's own numbers\n\n" + "\n".join(m))
    return "\n\n".join(parts) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log_dir")
    ap.add_argument("--out")
    ap.add_argument("--gap", type=float, default=None, help="seconds between calls for the cache model (default: log timestamps)")
    args = ap.parse_args()
    arms = [arm_stats(read_eval_log(info), args.gap) for info in list_eval_logs(args.log_dir)]
    arms = [a for a in arms if a["shifts"]]
    for a in arms:
        a["label"] = f"{a['strategy']} @ {a['threshold']}" if a["strategy"] != "none" else "none (full history)"
    text = render(sorted(arms, key=lambda a: a["label"]), "memory accuracy")
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
