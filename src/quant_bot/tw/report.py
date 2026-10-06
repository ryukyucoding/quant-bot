"""台股月營收月報：把選股與回測結果組成單一 HTML 頁面。

台股慣例：紅色 = 上漲 / 正報酬，綠色 = 下跌 / 負報酬。
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.svg_chart import Line, line_chart
from quant_bot.tw.pipeline import IN_SAMPLE_END, PRIMARY, Benchmark, MonthlyPicks, StrategyRun, summarize_window

TEMPLATES = Path(__file__).with_name("templates")
TEMPLATE = TEMPLATES / "report.html"
STYLE = TEMPLATES / "site.css"
LINE_CLASSES = ("s-base", "s-growth", "s-high", "s-primary")
STRATEGY_SHORT = ("全部等權", "營收年增", "營收創高", "主策略")
OOS_START = IN_SAMPLE_END + pd.Timedelta(days=1)


@dataclass(frozen=True)
class ReportData:
    picks: MonthlyPicks
    runs: list[StrategyRun]
    benchmarks: tuple[Benchmark, ...]  # 第一個是大盤
    generated_at: pd.Timestamp

    @property
    def market(self) -> Benchmark:
        return self.benchmarks[0]

    @property
    def primary(self) -> StrategyRun:
        return next(run for run in self.runs if run.config == PRIMARY)


def pct(value: float, digits: int = 1, signed: bool = True) -> str:
    if pd.isna(value):
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def tone(value: float) -> str:
    if pd.isna(value) or abs(value) < 1e-9:
        return "flat"
    return "up" if value > 0 else "down"


def _num(value: float, digits: int = 2) -> str:
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def _picks_rows(table: pd.DataFrame) -> str:
    rows = []
    for rank, (code, r) in enumerate(table.iterrows(), start=1):
        status_cls = "new" if r["status"] == "新進" else "hold"
        rows.append(
            "<tr>"
            f'<td class="num muted">{rank}</td>'
            f'<td><span class="code">{escape(code)}</span> {escape(str(r["name"]))}</td>'
            f'<td class="muted">{escape(str(r["industry"]))}</td>'
            f'<td class="num {tone(r["yoy_3"])}">{pct(r["yoy_3"])}</td>'
            f'<td class="num {tone(r["yoy_1"])}">{pct(r["yoy_1"])}</td>'
            f'<td class="num">{r["rev_3m"] / 1e5:,.1f}</td>'
            f'<td class="num">{_num(r["close"], 1)}</td>'
            f'<td class="num">{r["weight"] * 100:.0f}%</td>'
            f'<td><span class="chip {status_cls}">{r["status"]}</span></td>'
            "</tr>"
        )
    return "".join(rows)


def _dropped_list(dropped: pd.DataFrame) -> str:
    if dropped.empty:
        return '<p class="muted">上月持股本月全數續抱，沒有要賣出的股票。</p>'
    items = "".join(
        f'<li><span class="code">{escape(code)}</span> {escape(str(r["name"]))}</li>' for code, r in dropped.iterrows()
    )
    return f'<ul class="sell-list">{items}</ul>'


def _verdict(data: ReportData) -> str:
    """回答「有沒有贏大盤」：全期間、驗證期、逐年勝率、風險。"""
    strat, market = data.primary.result.equity, data.market.equity
    full_s, full_m = summarize_window(strat, None, None), summarize_window(market, None, None)
    oos_s, oos_m = summarize_window(strat, OOS_START, None), summarize_window(market, OOS_START, None)
    record = metrics.relative_to(strat, market)
    cells = [
        ("全期間年化", full_s["cagr"], full_m["cagr"]),
        (f"驗證期年化（{OOS_START.year}～）", oos_s["cagr"], oos_m["cagr"]),
    ]
    blocks = []
    for label, s, m in cells:
        diff = s - m
        blocks.append(
            '<div class="vs">'
            f'<span class="k">{label}</span>'
            f'<span class="big num {tone(diff)}">{pct(diff)}</span>'
            f'<span class="detail num">主策略 {pct(s)} ／ 大盤 {pct(m)}</span>'
            "</div>"
        )
    blocks.append(
        '<div class="vs">'
        '<span class="k">完整年度勝率</span>'
        f'<span class="big num">{record["years_won"]}<small> / {record["years_total"]} 年</small></span>'
        '<span class="detail">贏大盤的年數</span>'
        "</div>"
    )
    blocks.append(
        '<div class="vs">'
        '<span class="k">最大回撤</span>'
        f'<span class="big num down">{pct(full_s["max_drawdown"], 0, signed=False)}</span>'
        f'<span class="detail num">大盤 {pct(full_m["max_drawdown"], 0, signed=False)}</span>'
        "</div>"
    )
    return "".join(blocks)


def _metric_cells(equity: pd.Series, start, end) -> str:
    s = summarize_window(equity, start, end)
    return (
        f'<td class="num {tone(s["cagr"])}">{pct(s["cagr"])}</td>'
        f'<td class="num down-only">{pct(s["max_drawdown"], signed=False)}</td>'
        f'<td class="num">{_num(s["sharpe"])}</td>'
    )


def _summary_rows(data: ReportData) -> str:
    rows = []
    entries = [(run.config.name, run.result.equity, LINE_CLASSES[i], run) for i, run in enumerate(data.runs)]
    entries += [(b.label, b.equity, b.css_class, None) for b in data.benchmarks]
    for name, equity, css, run in entries:
        years = (equity.index[-1] - equity.index[0]).days / metrics.DAYS_PER_YEAR
        turnover = f"{run.result.turnover.mean() * 100:.0f}%" if run else "—"
        drag = pct(run.result.costs.sum() / years, 2, signed=False) if run else "—"
        is_primary = run is not None and run.config == PRIMARY
        is_market = equity is data.market.equity
        excess_value = float("nan") if is_market else metrics.relative_to(equity, data.market.equity)["excess_cagr"]
        excess, excess_tone = pct(excess_value), tone(excess_value)
        row_cls = "primary" if is_primary else ("market" if is_market else "")
        rows.append(
            f'<tr class="{row_cls}">'
            f'<th scope="row"><span class="swatch {css}"></span>{escape(name)}'
            f'{" <span class=chip>主策略</span>" if is_primary else ""}</th>'
            f'<td class="num {excess_tone} excess">{excess}</td>'
            f"{_metric_cells(equity, None, None)}"
            f"{_metric_cells(equity, None, IN_SAMPLE_END)}"
            f"{_metric_cells(equity, OOS_START, None)}"
            f'<td class="num">{turnover}</td><td class="num">{drag}</td>'
            "</tr>"
        )
    return "".join(rows)


def _yearly_table(data: ReportData) -> str:
    columns = [(short, run.result.equity, LINE_CLASSES[i]) for i, (run, short) in enumerate(zip(data.runs, STRATEGY_SHORT))]
    columns += [(b.short, b.equity, b.css_class) for b in data.benchmarks]
    yearly = pd.DataFrame({label: metrics.calendar_year_returns(eq) for label, eq, _ in columns})
    yearly["diff"] = yearly["主策略"] - yearly[data.market.short]

    head = "".join(
        f'<th scope="col" class="num"><span class="swatch {css}"></span>{label}</th>' for label, _, css in columns
    )
    head += '<th scope="col" class="num diff-col">主策略<br>− 大盤</th>'
    body = []
    for year, row in yearly.iterrows():
        partial = " *" if year in (yearly.index[0], yearly.index[-1]) else ""
        cells = "".join(f'<td class="num {tone(row[label])}">{pct(row[label])}</td>' for label, _, _ in columns)
        cells += f'<td class="num diff-col {tone(row["diff"])}">{pct(row["diff"])}</td>'
        body.append(f'<tr><th scope="row" class="num">{year}{partial}</th>{cells}</tr>')
    return f'<table class="yearly"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _charts(data: ReportData) -> tuple[str, str]:
    lines = [Line(run.config.name, run.result.equity, LINE_CLASSES[i]) for i, run in enumerate(data.runs)]
    lines += [Line(b.label, b.equity, b.css_class) for b in data.benchmarks]
    equity_svg = line_chart(lines, title="累積淨值（對數刻度）")

    dd_lines = [
        Line(PRIMARY.name, metrics.drawdown(data.primary.result.equity), "s-primary"),
        Line(data.market.label, metrics.drawdown(data.market.equity), data.market.css_class),
    ]
    dd_svg = line_chart(dd_lines, height=220, log_scale=False, y_format=lambda v: f"{v * 100:.0f}%", title="回撤")
    return equity_svg, dd_svg


def _legend(data: ReportData) -> str:
    items = [(run.config.name, LINE_CLASSES[i]) for i, run in enumerate(data.runs)]
    items += [(b.label, b.css_class) for b in data.benchmarks]
    return "".join(f'<li><span class="swatch {c}"></span>{escape(n)}</li>' for n, c in items)


def render(data: ReportData) -> str:
    picks = data.picks
    table = picks.table
    equity_svg, dd_svg = _charts(data)
    next_update = (picks.as_of.to_period("M") + 1).to_timestamp() + pd.Timedelta(days=10)
    replacements = {
        "{{PERIOD}}": f"{picks.period.year} 年 {picks.period.month} 月",
        "{{AS_OF}}": f"{picks.as_of:%Y-%m-%d}",
        "{{GENERATED}}": f"{data.generated_at:%Y-%m-%d %H:%M}",
        "{{NEXT_UPDATE}}": f"{next_update:%Y-%m-%d}",
        "{{N_PICKS}}": str(len(table)),
        "{{N_NEW}}": str(int((table["status"] == "新進").sum())) if len(table) else "0",
        "{{N_HOLD}}": str(int((table["status"] == "續抱").sum())) if len(table) else "0",
        "{{N_DROP}}": str(len(picks.dropped)),
        "{{PRIMARY_NAME}}": escape(PRIMARY.name),
        "{{TOP_N}}": str(PRIMARY.top_n),
        "{{PICK_ROWS}}": _picks_rows(table) if len(table) else "",
        "{{DROPPED}}": _dropped_list(picks.dropped),
        "{{VERDICT}}": _verdict(data),
        "{{SUMMARY_ROWS}}": _summary_rows(data),
        "{{IS_END}}": f"{IN_SAMPLE_END:%Y}",
        "{{OOS_START}}": f"{OOS_START.year}",
        "{{EQUITY_SVG}}": equity_svg,
        "{{DD_SVG}}": dd_svg,
        "{{LEGEND}}": _legend(data),
        "{{YEARLY}}": _yearly_table(data),
        "{{BT_START}}": f"{data.market.equity.index[0]:%Y-%m}",
        "{{STYLE}}": STYLE.read_text(encoding="utf-8"),
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html
