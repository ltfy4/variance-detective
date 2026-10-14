"""Dependency-free SVG charts for the HTML report (render identically everywhere, print well).

Colour roles follow a validated diverging scheme: favourable = blue, adverse = red, neutral = grey.
Signs and labels are always printed, so colour never carries meaning alone.
"""
from __future__ import annotations

from collections.abc import Callable
from html import escape

FAV, ADV, NEU, INK, GRID = "var(--fav)", "var(--adv)", "var(--neu)", "var(--ink-2)", "var(--grid)"


def waterfall(steps: list[tuple[str, float, str]], fmt: Callable[[float], str], *, width: int = 860, height: int = 320) -> str:
    """steps: [(label, value, kind)] with kind in {'start','delta','end'}; start/end are absolute levels."""
    if not steps:
        return ""
    levels: list[tuple[float, float]] = []
    running = 0.0
    for label, value, kind in steps:
        if kind in ("start", "end"):
            levels.append((value, value))
            running = value
        else:
            levels.append((running, running + value))
            running += value
    lo = min(min(a, b) for a, b in levels)
    hi = max(max(a, b) for a, b in levels)
    # Zoom the axis on the range the walk actually covers (a broken axis), otherwise the deltas
    # are invisible next to the absolute start/end bars. The floor is printed on the axis.
    rng = (hi - lo) or abs(hi) or 1.0
    if lo > 0 and rng < lo:
        lo = lo - rng * 0.35
    elif hi < 0 and rng < -hi:
        hi = hi + rng * 0.35
    else:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    pad_l, pad_r, pad_t, pad_b = 70, 20, 28, 70
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    span = (hi - lo) or 1.0
    y = lambda v: pad_t + (hi - v) / span * plot_h
    n = len(steps)
    slot = plot_w / n
    bar_w = min(64, slot * 0.62)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Variance waterfall">']
    # gridlines
    for i in range(5):
        v = lo + span * i / 4
        out.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{escape(fmt(v))}</text>')
    baseline = 0.0 if lo <= 0 <= hi else lo
    out.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(baseline):.1f}" y2="{y(baseline):.1f}" stroke="{INK}" stroke-width="1"/>')
    if baseline != 0:
        out.append(f'<text x="{width - pad_r}" y="{pad_t - 12}" text-anchor="end" class="tick">axis zoomed to the walk · starts at {escape(fmt(baseline))}</text>')
    prev_top = None
    for i, ((label, value, kind), (a, b)) in enumerate(zip(steps, levels)):
        x = pad_l + slot * i + (slot - bar_w) / 2
        if kind in ("start", "end"):
            a = baseline
        top, bottom = y(max(a, b)), y(min(a, b))
        h = max(bottom - top, 1.5)
        color = NEU if kind in ("start", "end") else (FAV if value >= 0 else ADV)
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="3" fill="{color}"><title>{escape(label)}: {escape(fmt(value))}</title></rect>')
        if prev_top is not None and kind == "delta":
            out.append(f'<line x1="{x - (slot - bar_w) / 2:.1f}" x2="{x:.1f}" y1="{y(a):.1f}" y2="{y(a):.1f}" stroke="{INK}" stroke-dasharray="3 3" stroke-width="1"/>')
        prev_top = top
        lbl = fmt(value) if kind == "delta" else fmt(b)
        out.append(f'<text x="{x + bar_w / 2:.1f}" y="{top - 6:.1f}" text-anchor="middle" class="val">{escape(lbl)}</text>')
        words = _wrap(label, 14)
        for j, w in enumerate(words[:3]):
            out.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - pad_b + 18 + j * 14:.1f}" text-anchor="middle" class="tick">{escape(w)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def hbars(rows: list[tuple[str, float, str | None]], fmt: Callable[[float], str], *, width: int = 860, row_h: int = 30) -> str:
    """Horizontal diverging bars: rows = [(label, value, note)]."""
    if not rows:
        return ""
    m = max(abs(v) for _, v, _ in rows) or 1.0
    label_w = int(width * 0.36)
    note_w = int(width * 0.13) if any(n for _, _, n in rows) else 10
    plot_w = width - label_w - note_w - 20
    zero_x = label_w + plot_w / 2
    height = row_h * len(rows) + 10
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Contributions">']
    out.append(f'<line x1="{zero_x}" x2="{zero_x}" y1="4" y2="{height - 4}" stroke="{INK}" stroke-width="1"/>')
    for i, (label, v, note) in enumerate(rows):
        yy = 5 + i * row_h
        w = abs(v) / m * (plot_w / 2 - 6)
        x = zero_x if v >= 0 else zero_x - w
        color = FAV if v >= 0 else ADV
        out.append(f'<text x="{label_w - 10}" y="{yy + row_h / 2 + 4}" text-anchor="end" class="lbl">{escape(_trunc(label, 38))}</text>')
        out.append(f'<rect x="{x:.1f}" y="{yy + 7}" width="{max(w, 1.5):.1f}" height="{row_h - 14}" rx="3" fill="{color}"><title>{escape(label)}: {escape(fmt(v))}</title></rect>')
        # value label sits on the empty side of the zero line, so it never collides with the bar or the row label
        tx = zero_x - 6 if v >= 0 else zero_x + 6
        anchor = "end" if v >= 0 else "start"
        out.append(f'<text x="{tx:.1f}" y="{yy + row_h / 2 + 4}" text-anchor="{anchor}" class="val">{escape(fmt(v))}</text>')
        if note:
            out.append(f'<text x="{width - 4}" y="{yy + row_h / 2 + 4}" text-anchor="end" class="tick">{escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def _wrap(s: str, n: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines or [s]


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
