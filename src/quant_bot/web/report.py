"""月報頁面：把選股與回測結果組成單一 HTML。市場相關的文字與欄位來自 MarketSpec。

顏色採台股慣例：紅色 = 上漲 / 正報酬，綠色 = 下跌 / 負報酬（美股頁也一樣，網站讀者是台灣投資人）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.portfolio import Benchmark, MonthlyPicks, StrategyRun, summarize_window
from quant_bot.common.svg_chart import Line, line_chart
from quant_bot.web.ai_section import render_ai_section, severity_chip
from quant_bot.web.spec import MarketSpec, num, pct, tone

TEMPLATES = Path(__file__).with_name("templates")
TEMPLATE = TEMPLATES / "report.html"
STYLE = TEMPLATES / "site.css"
LINE_CLASSES = ("s-base", "s-growth", "s-high", "s-primary")


@dataclass(frozen=True)
class ReportData:
    spec: MarketSpec
    picks: MonthlyPicks
    runs: list[StrategyRun]
    benchmarks: tuple[Benchmark, ...]  # 第一個是大盤
    generated_at: pd.Timestamp
    ai_reviews: Mapping[str, object] | None = None  # None = 這個市場不做 AI 檢查

    @property
    def market(self) -> Benchmark:
        return self.benchmarks[0]

    @property
    def primary(self) -> StrategyRun:
        return next(run for run in self.runs if run.config.name == self.spec.primary_name)


def _picks_table(data: ReportData) -> str:
    spec, table = data.spec, data.picks.table
    reviews = data.ai_reviews
    head = "".join(c.header for c in spec.pick_columns) + ('<th>風險檢查</th>' if reviews else "")
    rows = []
    for rank, (code, r) in enumerate(table.iterrows(), start=1):
        status_cls = "new" if r["status"] == "新進" else "hold"
        cells = "".join(c.cell(r) for c in spec.pick_columns)
        if reviews:
            review = reviews.get(code)
            cells += f"<td>{severity_chip(review.severity) if review else ''}</td>"
        rows.append(
            "<tr>"
            f'<td class="num muted">{rank}</td>'
            f'<td><span class="code">{escape(code)}</span> {escape(str(r["name"]))}</td>'
            f"{cells}"
            f'<td class="num">{r["weight"] * 100:.0f}%</td>'
            f'<td><span class="chip {status_cls}">{r["status"]}</span></td>'
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="99" class="muted">本月沒有符合條件的股票，持有現金。</td></tr>'
    return (
        '<table><thead><tr><th class="num">#</th><th>股票</th>'
        f'{head}<th class="num">權重</th><th>狀態</th></tr></thead><tbody>{body}</tbody></table>'
    )


def _dropped_list(dropped: pd.DataFrame) -> str:
    if dropped.empty:
        return '<p class="muted">上月持股本月全數續抱，沒有要賣出的股票。</p>'
    items = "".join(
        f'<li><span class="code">{escape(code)}</span> {escape(str(r["name"]))}</li>' for code, r in dropped.iterrows()
    )
    return f'<ul class="sell-list">{items}</ul>'


def _verdict(data: ReportData) -> str:
    """回答「有沒有贏大盤」：全期間、驗證期、逐年勝率、風險。"""
    oos = data.spec.oos_start
    strat, market = data.primary.result.equity, data.market.equity
    full_s, full_m = summarize_window(strat, None, None), summarize_window(market, None, None)
    oos_s, oos_m = summarize_window(strat, oos, None), summarize_window(market, oos, None)
    record = metrics.relative_to(strat, market)
    blocks = []
    for label, s, m in (("全期間年化", full_s["cagr"], full_m["cagr"]), (f"驗證期年化（{oos.year}～）", oos_s["cagr"], oos_m["cagr"])):
        blocks.append(
            f'<div class="vs"><span class="k">{label}</span>'
            f'<span class="big num {tone(s - m)}">{pct(s - m)}</span>'
            f'<span class="detail num">主策略 {pct(s)} ／ 大盤 {pct(m)}</span></div>'
        )
    blocks.append(
        '<div class="vs"><span class="k">完整年度勝率</span>'
        f'<span class="big num">{record["years_won"]}<small> / {record["years_total"]} 年</small></span>'
        '<span class="detail">贏大盤的年數</span></div>'
    )
    blocks.append(
        '<div class="vs"><span class="k">最大回撤</span>'
        f'<span class="big num down">{pct(full_s["max_drawdown"], 0, signed=False)}</span>'
        f'<span class="detail num">大盤 {pct(full_m["max_drawdown"], 0, signed=False)}</span></div>'
    )
    return "".join(blocks)


def _metric_cells(equity: pd.Series, start, end) -> str:
    s = summarize_window(equity, start, end)
    return (
        f'<td class="num {tone(s["cagr"])}">{pct(s["cagr"])}</td>'
        f'<td class="num down-only">{pct(s["max_drawdown"], signed=False)}</td>'
        f'<td class="num">{num(s["sharpe"])}</td>'
    )


def _summary_rows(data: ReportData) -> str:
    spec = data.spec
    entries = [(run.config.name, run.result.equity, LINE_CLASSES[i], run) for i, run in enumerate(data.runs)]
    entries += [(b.label, b.equity, b.css_class, None) for b in data.benchmarks]
    rows = []
    for name, equity, css, run in entries:
        years = (equity.index[-1] - equity.index[0]).days / metrics.DAYS_PER_YEAR
        turnover = f"{run.result.turnover.mean() * 100:.0f}%" if run else "—"
        drag = pct(run.result.costs.sum() / years, 2, signed=False) if run else "—"
        is_primary = run is not None and run.config.name == spec.primary_name
        is_market = equity is data.market.equity
        excess = float("nan") if is_market else metrics.relative_to(equity, data.market.equity)["excess_cagr"]
        row_cls = "primary" if is_primary else ("market" if is_market else "")
        rows.append(
            f'<tr class="{row_cls}"><th scope="row"><span class="swatch {css}"></span>{escape(name)}'
            f'{" <span class=chip>主策略</span>" if is_primary else ""}</th>'
            f'<td class="num {tone(excess)} excess">{pct(excess)}</td>'
            f"{_metric_cells(equity, None, None)}"
            f"{_metric_cells(equity, None, spec.in_sample_end)}"
            f"{_metric_cells(equity, spec.oos_start, None)}"
            f'<td class="num">{turnover}</td><td class="num">{drag}</td></tr>'
        )
    return "".join(rows)


def _yearly_table(data: ReportData) -> str:
    shorts = data.spec.strategy_short
    columns = [(shorts[i], run.result.equity, LINE_CLASSES[i]) for i, run in enumerate(data.runs)]
    columns += [(b.short, b.equity, b.css_class) for b in data.benchmarks]
    yearly = pd.DataFrame({label: metrics.calendar_year_returns(eq) for label, eq, _ in columns})
    primary_short = shorts[next(i for i, r in enumerate(data.runs) if r.config.name == data.spec.primary_name)]
    diff = yearly[primary_short] - yearly[data.market.short]

    head = "".join(f'<th scope="col" class="num"><span class="swatch {css}"></span>{label}</th>' for label, _, css in columns)
    head += '<th scope="col" class="num diff-col">主策略<br>− 大盤</th>'
    body = []
    for year, row in yearly.iterrows():
        partial = " *" if year in (yearly.index[0], yearly.index[-1]) else ""
        cells = "".join(f'<td class="num {tone(row[label])}">{pct(row[label])}</td>' for label, _, _ in columns)
        cells += f'<td class="num diff-col {tone(diff[year])}">{pct(diff[year])}</td>'
        body.append(f'<tr><th scope="row" class="num">{year}{partial}</th>{cells}</tr>')
    return f'<table class="yearly"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _charts(data: ReportData) -> tuple[str, str]:
    lines = [Line(run.config.name, run.result.equity, LINE_CLASSES[i]) for i, run in enumerate(data.runs)]
    lines += [Line(b.label, b.equity, b.css_class) for b in data.benchmarks]
    equity_svg = line_chart(lines, title="累積淨值（對數刻度）")
    dd_lines = [
        Line(data.spec.primary_name, metrics.drawdown(data.primary.result.equity), "s-primary"),
        Line(data.market.label, metrics.drawdown(data.market.equity), data.market.css_class),
    ]
    dd_svg = line_chart(dd_lines, height=220, log_scale=False, y_format=lambda v: f"{v * 100:.0f}%", title="回撤")
    return equity_svg, dd_svg


def _legend(data: ReportData) -> str:
    items = [(run.config.name, LINE_CLASSES[i]) for i, run in enumerate(data.runs)]
    items += [(b.label, b.css_class) for b in data.benchmarks]
    return "".join(f'<li><span class="swatch {c}"></span>{escape(n)}</li>' for n, c in items)


def render(data: ReportData) -> str:
    spec, picks = data.spec, data.picks
    table = picks.table
    equity_svg, dd_svg = _charts(data)
    next_date, next_note = spec.next_update(picks.as_of)
    bt_intro = spec.backtest_intro_html.format(
        BT_START=f"{data.market.equity.index[0]:%Y-%m}", IS_END=spec.in_sample_end.year, OOS_START=spec.oos_start.year
    )
    replacements = {
        "{{PAGE_TITLE}}": escape(f"{spec.name}月報"),
        "{{EYEBROW}}": escape(spec.eyebrow),
        "{{COVER_TITLE}}": escape(spec.cover_title(picks.period)),
        "{{AS_OF}}": f"{picks.as_of:%Y-%m-%d}",
        "{{GENERATED}}": f"{data.generated_at:%Y-%m-%d %H:%M}",
        "{{NEXT_UPDATE}}": f"{next_date:%Y-%m-%d}",
        "{{NEXT_UPDATE_NOTE}}": escape(next_note),
        "{{N_PICKS}}": str(len(table)),
        "{{N_NEW}}": str(int((table["status"] == "新進").sum())) if len(table) else "0",
        "{{N_HOLD}}": str(int((table["status"] == "續抱").sum())) if len(table) else "0",
        "{{N_DROP}}": str(len(picks.dropped)),
        "{{METHOD}}": spec.method_html,
        "{{PICKS_TABLE}}": _picks_table(data),
        "{{DROPPED}}": _dropped_list(picks.dropped),
        "<!--AI_REVIEW-->": render_ai_section(data.ai_reviews, list(table.index)),
        "{{BT_INTRO}}": bt_intro,
        "{{MARKET_NOTE}}": escape(spec.market_note),
        "{{VERDICT}}": _verdict(data),
        "{{SUMMARY_ROWS}}": _summary_rows(data),
        "{{IS_END}}": f"{spec.in_sample_end:%Y}",
        "{{OOS_START}}": f"{spec.oos_start.year}",
        "{{EQUITY_SVG}}": equity_svg,
        "{{DD_SVG}}": dd_svg,
        "{{LEGEND}}": _legend(data),
        "{{YEARLY}}": _yearly_table(data),
        "{{NOTES}}": spec.notes_html,
        "{{SOURCES}}": escape(spec.sources),
        "{{STYLE}}": STYLE.read_text(encoding="utf-8"),
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html
