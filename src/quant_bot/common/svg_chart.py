"""產生無外部依賴的 SVG 折線圖。顏色以 CSS class 指定，交給頁面的主題 token 決定。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape

import pandas as pd

MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 52, 16, 12, 28
LOG_TICK_CANDIDATES = (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64)


@dataclass(frozen=True)
class Line:
    label: str
    series: pd.Series
    css_class: str


def _log_ticks(lo: float, hi: float) -> list[float]:
    ticks = [t for t in LOG_TICK_CANDIDATES if lo <= t <= hi]
    while len(ticks) > 7:
        ticks = ticks[::2]
    return ticks


def _linear_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=raw)
    start = math.ceil(lo / step) * step
    return [start + i * step for i in range(int((hi - start) / step) + 1)]


def line_chart(
    lines: list[Line],
    *,
    width: int = 960,
    height: int = 340,
    log_scale: bool = True,
    y_format=lambda v: f"{v:g}×",
    title: str = "",
) -> str:
    frames = [ln.series.dropna() for ln in lines]
    x0 = min(f.index[0] for f in frames)
    x1 = max(f.index[-1] for f in frames)
    y_lo = min(f.min() for f in frames)
    y_hi = max(f.max() for f in frames)

    transform = math.log if log_scale else (lambda v: v)
    if log_scale:
        y_lo, y_hi = y_lo * 0.95, y_hi * 1.05
    else:
        pad = (y_hi - y_lo) * 0.05 or 0.01
        y_lo, y_hi = y_lo - pad, y_hi + pad
    t_lo, t_hi = transform(y_lo), transform(y_hi)

    plot_w = width - MARGIN_LEFT - MARGIN_RIGHT
    plot_h = height - MARGIN_TOP - MARGIN_BOTTOM
    span = (x1 - x0).total_seconds()

    def px(ts: pd.Timestamp) -> float:
        return MARGIN_LEFT + (ts - x0).total_seconds() / span * plot_w

    def py(value: float) -> float:
        return MARGIN_TOP + (t_hi - transform(value)) / (t_hi - t_lo) * plot_h

    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}" '
        'preserveAspectRatio="xMidYMid meet">'
    ]
    ticks = _log_ticks(y_lo, y_hi) if log_scale else _linear_ticks(y_lo, y_hi)
    for tick in ticks:
        y = py(tick)
        parts.append(f'<line class="grid" x1="{MARGIN_LEFT}" x2="{width - MARGIN_RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{MARGIN_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(y_format(tick))}</text>')

    years = range(x0.year + 1, x1.year + 1)
    step = 1 if len(years) <= 8 else 2
    for year in list(years)[::step]:
        x = px(pd.Timestamp(year=year, month=1, day=1))
        parts.append(f'<text class="tick" x="{x:.1f}" y="{height - 8}" text-anchor="middle">{year}</text>')

    for line, frame in zip(lines, frames):
        sampled = frame.resample("W").last().dropna()
        points = " ".join(f"{px(ts):.1f},{py(v):.1f}" for ts, v in sampled.items())
        parts.append(f'<polyline class="line {line.css_class}" points="{points}"><title>{escape(line.label)}</title></polyline>')
        last_ts, last_v = sampled.index[-1], sampled.iloc[-1]
        parts.append(f'<circle class="dot {line.css_class}" cx="{px(last_ts):.1f}" cy="{py(last_v):.1f}" r="3.5"/>')

    parts.append("</svg>")
    return "".join(parts)


def bar_chart(
    labels: list[str],
    values: list[float],
    css_classes: list[str],
    *,
    width: int = 960,
    height: int = 220,
    y_format=lambda v: f"{v:,.0f}",
    title: str = "",
    label_every: int = 6,
) -> str:
    """直條圖（值須 ≥ 0）。每根長條的顏色由 css_classes 指定。"""
    if not values:
        return ""
    top = max(values) * 1.08 or 1.0
    plot_w = width - MARGIN_LEFT - MARGIN_RIGHT
    plot_h = height - MARGIN_TOP - MARGIN_BOTTOM
    slot = plot_w / len(values)
    bar_w = max(slot * 0.7, 1.0)

    def py(value: float) -> float:
        return MARGIN_TOP + (1 - value / top) * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">']
    for tick in _linear_ticks(0, top, count=4):
        y = py(tick)
        parts.append(f'<line class="grid" x1="{MARGIN_LEFT}" x2="{width - MARGIN_RIGHT}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{MARGIN_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">{escape(y_format(tick))}</text>')
    for i, (label, value, css) in enumerate(zip(labels, values, css_classes)):
        x = MARGIN_LEFT + i * slot + (slot - bar_w) / 2
        y = py(max(value, 0))
        parts.append(
            f'<rect class="bar {css}" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{MARGIN_TOP + plot_h - y:.1f}">'
            f"<title>{escape(label)}：{escape(y_format(value))}</title></rect>"
        )
        if i % label_every == 0:
            parts.append(f'<text class="tick" x="{x + bar_w / 2:.1f}" y="{height - 8}" text-anchor="middle">{escape(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)
