"""Draw the pause-between-turns chart from docs/results/sweeps.md as light and dark SVGs.

    python -m longhaul.chart
"""
from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
              "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
             "series": ["#3987e5", "#d95926", "#199e70", "#c98500"]},
}
# column in the sweep table -> label on the chart, in fixed colour order
SERIES = [("none (full history)", "Full history", "Full history"),
          ("full history, 5-minute cache only", "Full history, 5-minute cache only", "5-minute cache only"),
          ("edit, keep 3 tool results", "Edit (clears old tool results)", "Edit"), ("summary", "Summary", "Summary")]
REFERENCE = "full history, no cache"
W, H, LEFT, RIGHT, TOP, BOTTOM = 860, 440, 56, 210, 92, 52
Y_MIN, Y_MAX, TICKS = 1.0, 50.0, [1, 2, 5, 10, 20, 50]


def read_table() -> tuple[list[str], dict[str, list[float]]]:
    lines = (ROOT / "docs/results/sweeps.md").read_text().split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("| pause between turns"))
    header = [c.strip() for c in lines[start].strip("|").split("|")]
    pauses, cols = [], {h: [] for h in header[1:]}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        pauses.append(cells[0])
        for h, c in zip(header[1:], cells[1:]):
            cols[h].append(float(c))
    return pauses, cols


def pause_label(text: str) -> str:
    m = re.match(r"(\d+) s", text)
    if m and int(m.group(1)) >= 100:
        return f"{int(m.group(1)) / 60:.1f} min".replace(".0", "")
    return text


def render(theme: dict, pauses: list[str], cols: dict[str, list[float]]) -> str:
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM
    x = lambda i: LEFT + pw * i / (len(pauses) - 1)
    y = lambda v: TOP + ph * (1 - (math.log10(v) - math.log10(Y_MIN)) / (math.log10(Y_MAX) - math.log10(Y_MIN)))
    font = 'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif"'
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
         f'aria-label="Cost per shift against the pause between operator turns, for four context strategies">',
         f'<rect width="{W}" height="{H}" fill="{theme["surface"]}"/>',
         f'<text x="{LEFT}" y="28" {font} font-size="16" font-weight="600" fill="{theme["ink"]}">A pause longer than the cache lifetime changes which strategy is cheapest</text>',
         f'<text x="{LEFT}" y="48" {font} font-size="12" fill="{theme["ink2"]}">Modelled cost per 120-turn shift on Claude Opus 5.5 (USD, log scale) by pause between operator turns. Offline estimate.</text>']
    lx = LEFT                                                           # legend row
    for (_, label, _short), colour in zip(SERIES, theme["series"]):
        o.append(f'<line x1="{lx}" y1="68" x2="{lx + 18}" y2="68" stroke="{colour}" stroke-width="2"/>'
                 f'<circle cx="{lx + 9}" cy="68" r="4" fill="{colour}"/>'
                 f'<text x="{lx + 24}" y="72" {font} font-size="12" fill="{theme["ink2"]}">{label}</text>')
        lx += 38 + 6.4 * len(label)
    lx += 18
    o.append(f'<line x1="{lx}" y1="68" x2="{lx + 18}" y2="68" stroke="{theme["muted"]}" stroke-width="1.5" stroke-dasharray="4 3"/>'
             f'<text x="{lx + 24}" y="72" {font} font-size="12" fill="{theme["ink2"]}">No cache</text>')
    for t in TICKS:                                                     # grid and y axis
        o.append(f'<line x1="{LEFT}" y1="{y(t):.1f}" x2="{LEFT + pw}" y2="{y(t):.1f}" stroke="{theme["grid"]}" stroke-width="1"/>'
                 f'<text x="{LEFT - 8}" y="{y(t) + 4:.1f}" {font} font-size="11" text-anchor="end" fill="{theme["muted"]}">${t}</text>')
    for i, p in enumerate(pauses):
        o.append(f'<text x="{x(i):.1f}" y="{TOP + ph + 20}" {font} font-size="11" text-anchor="middle" fill="{theme["muted"]}">{pause_label(p)}</text>')
    for after, label in ((2, "5-minute cache lifetime"), (5, "1 hour")):  # where a cache lifetime runs out
        bx = (x(after) + x(after + 1)) / 2
        o.append(f'<line x1="{bx:.1f}" y1="{TOP}" x2="{bx:.1f}" y2="{TOP + ph}" stroke="{theme["muted"]}" stroke-width="1" stroke-dasharray="2 4"/>'
                 f'<text x="{bx - 6:.1f}" y="{TOP + 12}" {font} font-size="11" text-anchor="end" fill="{theme["ink2"]}">{label}</text>')
    ref = cols[REFERENCE]
    o.append(f'<line x1="{LEFT}" y1="{y(ref[0]):.1f}" x2="{LEFT + pw}" y2="{y(ref[0]):.1f}" stroke="{theme["muted"]}" stroke-width="1.5" stroke-dasharray="4 3"/>')
    ends = [(y(ref[-1]), f"No cache ${ref[-1]:.2f}", None)]
    for (col, _label, short), colour in zip(SERIES, theme["series"]):
        vals = cols[col]
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>')
        o += [f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="{colour}" stroke="{theme["surface"]}" stroke-width="2"/>' for i, v in enumerate(vals)]
        ends.append((y(vals[-1]), f"{short} ${vals[-1]:.2f}", colour))
    ends.sort(key=lambda e: e[0])                                       # direct labels, nudged apart
    placed = []
    for ty, text, colour in ends:
        ly = ty if not placed else max(ty, placed[-1] + 15)
        placed.append(ly)
        if colour:
            o.append(f'<circle cx="{LEFT + pw + 14}" cy="{ly:.1f}" r="4" fill="{colour}"/>')
        o.append(f'<text x="{LEFT + pw + 24}" y="{ly + 4:.1f}" {font} font-size="12" fill="{theme["ink"]}">{text}</text>')
    first = cols[SERIES[0][0]][0]
    o.append(f'<text x="{LEFT + 8}" y="{y(first) - 10:.1f}" {font} font-size="12" fill="{theme["ink"]}">${first:.2f} with caching</text>')
    return "\n".join(o) + "\n</svg>\n"


def main() -> None:
    pauses, cols = read_table()
    for name, theme in THEMES.items():
        path = ROOT / f"docs/img/pause-cost-{name}.svg"
        path.write_text(render(theme, pauses, cols))
        print(path)


if __name__ == "__main__":
    main()
