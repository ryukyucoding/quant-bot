"""把月報濃縮成一則 Telegram 訊息：要買、要賣、續抱、跟大盤比。台股慣例紅買綠賣。"""

from __future__ import annotations

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.portfolio import summarize_window
from quant_bot.common.telegram import escape
from quant_bot.web.report import ReportData
from quant_bot.web.spec import pct

DISCLAIMER = "研究工具，不是投資建議。"


def _stock_line(code: str, row: pd.Series, growth: tuple[str, str] | None) -> str:
    extra = f"  {growth[1]} {pct(row[growth[0]], 0)}" if growth else ""
    return f"<code>{escape(code)}</code> {escape(row['name'])}{extra}"


def _ai_lines(data: ReportData) -> list[str]:
    if not data.ai_reviews:
        return []
    flagged = [r for r in data.ai_reviews.values() if r.severity == "high"]
    if not flagged:
        return ["🔎 新聞與重大訊息檢查：本月名單沒有發現高風險事件。", ""]
    lines = [f"⚠️ <b>新聞與重大訊息標記高風險（{len(flagged)}）</b>，實驗名單「風險篩選版」會排除這些股票"]
    for review in flagged:
        categories = "、".join(dict.fromkeys(f["category"] for f in review.flags)) or "見報告"
        lines.append(f"<code>{escape(review.code)}</code> {escape(review.name)}：{escape(categories)}")
    return [*lines, "檢查可能誤判，請看報告中的出處自行查證。", ""]


def format_monthly_message(data: ReportData, report_url: str | None = None) -> str:
    spec, picks = data.spec, data.picks
    table = picks.table
    new = table[table["status"] == "新進"]
    hold = table[table["status"] == "續抱"]
    weight = f"{table['weight'].iloc[0] * 100:.0f}%" if len(table) else "—"
    growth = (spec.growth_field, spec.growth_label)

    strat, market = data.primary.result.equity, data.market.equity
    full_s, full_m = summarize_window(strat, None, None), summarize_window(market, None, None)
    record = metrics.relative_to(strat, market)

    lines = [
        f"<b>{escape(spec.name)}｜{escape(spec.cover_title(picks.period))}</b>",
        f"股價資料至 {picks.as_of:%Y-%m-%d}，共 {len(table)} 檔，每檔 {weight}",
        "",
        f"🔴 <b>新進，要買（{len(new)}）</b>",
        *([_stock_line(c, r, growth) for c, r in new.iterrows()] or ["（無）"]),
        "",
        f"🟢 <b>剔除，要賣（{len(picks.dropped)}）</b>",
        *([_stock_line(c, r, None) for c, r in picks.dropped.iterrows()] or ["（無）"]),
        "",
        f"⚪ <b>續抱（{len(hold)}）</b>",
        "、".join(f"{escape(c)} {escape(r['name'])}" for c, r in hold.iterrows()) or "（無）",
        "",
        *_ai_lines(data),
        f"<b>回測 vs 大盤</b>　{escape(spec.primary_name)}",
        f"年化 {pct(full_s['cagr'])} vs {pct(full_m['cagr'])}（{pct(record['excess_cagr'])}）",
        f"完整年度贏 {record['years_won']} / {record['years_total']} 年",
        f"最大回撤 {pct(full_s['max_drawdown'], 0, signed=False)} vs {pct(full_m['max_drawdown'], 0, signed=False)}",
        "",
    ]
    if report_url:
        lines.append(f'<a href="{escape(report_url)}">完整報告</a>（附件為本月 HTML 版）')
    else:
        lines.append("完整報告見附件 HTML。")
    lines.append(f"<i>{DISCLAIMER}</i>")
    return "\n".join(lines)
