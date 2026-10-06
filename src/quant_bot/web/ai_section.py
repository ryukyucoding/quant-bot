"""報告頁的「新聞與重大訊息檢查」區塊（關鍵字規則或 AI）。內容來自外部資料，一律跳脫後再輸出。"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

SEVERITY_LABEL = {"high": "高風險", "watch": "留意", "none": "無明顯風險", "error": "未完成"}
SEVERITY_ORDER = {"high": 0, "watch": 1, "error": 2, "none": 3}


def severity_chip(severity: str) -> str:
    return f'<span class="chip risk-{escape(severity)}">{SEVERITY_LABEL.get(severity, severity)}</span>'


def _source_html(key: str, source) -> str:
    label = f"{escape(source.date)} {escape(source.title)}"
    if source.kind == "news" and source.link.startswith("https://"):
        return f'<a href="{escape(source.link)}" rel="noopener nofollow">{label}</a>'
    return f"重大訊息 {label}"


def _card(review) -> str:
    flags = "".join(
        f"<li><b>{escape(f['category'])}</b>：{escape(f['description'])}"
        + "".join(f'<span class="src">{_source_html(s, review.sources[s])}</span>' for s in f["sources"] if s in review.sources)
        + "</li>"
        for f in review.flags
    )
    flags_html = f'<ul class="ai-flags">{flags}</ul>' if flags else ""
    return (
        f'<article class="ai-card risk-{escape(review.severity)}">'
        f'<header><span class="code">{escape(review.code)}</span> <b>{escape(review.name)}</b> {severity_chip(review.severity)}</header>'
        f"<p>{escape(review.summary)}</p>{flags_html}</article>"
    )


RULES_INTRO = (
    "依固定的關鍵字規則，檢查每檔入選股近 60 天的公開資訊觀測站重大訊息與近 30 天新聞標題，"
    "例如現金增資、更換會計師事務所、檢調搜索、停工、全額交割、經營層異動。規則可能誤判或漏判，請點出處自行查證。"
)
AI_INTRO = (
    "由 AI（Claude）閱讀每檔入選股近 60 天的公開資訊觀測站重大訊息與近 30 天新聞標題後整理。"
    "AI 可能看錯或漏看，請點出處自行查證。"
)


def render_ai_section(reviews: Mapping[str, object] | None, codes: list[str]) -> str:
    if reviews is None:
        return ""
    uses_ai = any(getattr(r, "model", "").startswith("claude") for r in reviews.values())
    if not reviews:
        body = '<p class="muted">本月沒有執行檢查。</p>'
        counts = ""
    else:
        ordered = sorted((reviews[c] for c in codes if c in reviews), key=lambda r: SEVERITY_ORDER.get(r.severity, 9))
        tally = {k: sum(r.severity == k for r in ordered) for k in ("high", "watch", "none")}
        counts = (
            '<div class="tally">'
            f'<div><span class="n risk-text-high">{tally["high"]}</span><span class="k">高風險</span></div>'
            f'<div><span class="n risk-text-watch">{tally["watch"]}</span><span class="k">留意</span></div>'
            f'<div><span class="n">{tally["none"]}</span><span class="k">無明顯風險</span></div></div>'
        )
        body = '<div class="ai-list">' + "".join(_card(r) for r in ordered) + "</div>"
    return (
        '<section aria-labelledby="ai-h"><div class="section-head">'
        '<h2 id="ai-h">新聞與重大訊息檢查</h2>'
        f'<p class="muted">{AI_INTRO if uses_ai else RULES_INTRO}'
        "被標為「高風險」的股票不會出現在實驗名單「風險篩選版」裡，兩份名單的實際表現都記錄在歷史紀錄頁。</p></div>"
        f"{counts}{body}</section>"
    )
