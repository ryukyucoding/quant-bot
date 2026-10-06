"""個股查詢：每檔一頁（條件檢查、月營收、入選紀錄、風險檢查）＋可搜尋的總表。

頁面放在 site/stocks/，樣式改用共用的 site/assets/site.css（1,800 多頁不重複內嵌 CSS）。
總表的搜尋是唯一的 JavaScript，以 CSP 的 sha256 雜湊只允許這段程式執行。
"""

from __future__ import annotations

import base64
import hashlib
from html import escape

import pandas as pd

from quant_bot.common.svg_chart import bar_chart
from quant_bot.tw.stock_profiles import StockProfile
from quant_bot.web.ai_section import severity_chip
from quant_bot.web.spec import pct, tone

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
    '&family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@700;900&display=swap">\n'
)
STYLESHEET = '<link rel="stylesheet" href="../assets/site.css">\n'
FOOTER = (
    "<footer><!--SITE_FOOTER-->資料來源：公開資訊觀測站月營收彙總表與重大訊息、臺灣證券交易所發行量加權股價報酬指數、"
    "Yahoo Finance。入選紀錄中「回測」的期別是用同一套規則事後計算，「實際發布」才是當時公開的名單。</footer>"
)
SEARCH_SCRIPT = (
    "const q=document.getElementById('q'),n=document.getElementById('count'),"
    "rows=[...document.querySelectorAll('#stocks tbody tr')];"
    "function f(){const v=q.value.trim().toLowerCase();let c=0;"
    "for(const r of rows){const ok=!v||r.dataset.key.includes(v);r.hidden=!ok;if(ok)c++;}n.textContent=c;}"
    "q.addEventListener('input',f);"
    "q.addEventListener('keydown',e=>{if(e.key!=='Enter')return;"
    "const v=rows.filter(r=>!r.hidden);const exact=v.find(r=>r.dataset.code===q.value.trim());"
    "const t=exact||(v.length===1?v[0]:null);if(t)location.href=t.querySelector('a').href;});"
)
SEARCH_SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(SEARCH_SCRIPT.encode()).digest()).decode()


def _head(title: str) -> str:
    return f"<title>{escape(title)}</title>\n{FONTS}{STYLESHEET}"


# ---------- 個股頁 ----------

def _status_sentence(p: StockProfile) -> str:
    failed = [c.label for c in p.checks if not c.passed]
    if p.picked:
        return f"<b>本月入選</b>主策略名單，在合格股票中依近三月營收年增排第 {p.rank} 名。"
    if not failed:
        return f"符合所有條件，但近三月營收年增在合格股票中排第 {p.rank} 名，沒有進前 20 名。"
    return "沒有入選：未通過「" + "」「".join(escape(f) for f in failed) + "」。"


def _checks_table(p: StockProfile) -> str:
    rows = "".join(
        f'<tr><th scope="row">{escape(c.label)}</th>'
        f'<td class="{"check-pass" if c.passed else "check-fail"}">{"✓ 通過" if c.passed else "✗ 未通過"}</td>'
        f'<td class="muted">{escape(c.detail)}</td></tr>'
        for c in p.checks
    )
    return f'<table class="checks"><tbody>{rows}</tbody></table>'


def _revenue_chart(p: StockProfile) -> str:
    rev = p.revenue.dropna(subset=["revenue"])
    if rev.empty:
        return '<p class="muted">沒有月營收資料。</p>'
    classes = [tone(y) if pd.notna(y) else "flat" for y in rev["yoy_1"]]
    labels = [str(x) for x in rev["period"]]
    chart = bar_chart(labels, list(rev["revenue"] / 1e5), classes, y_format=lambda v: f"{v:,.1f}", title="月營收（億元）")
    return (
        '<ul class="legend"><li><span class="swatch bar-up"></span>比去年同月高</li>'
        '<li><span class="swatch bar-down"></span>比去年同月低</li></ul>' + chart
    )


def _selections(p: StockProfile) -> str:
    s = p.selections
    if s.empty:
        return '<p class="muted">2014 年以來沒有入選過主策略名單。</p>'
    settled = s[~s["ongoing"]]
    excess = settled["ret"] - settled["market_ret"]
    summary = (
        f'<p class="muted">共入選 {len(s)} 次（實際發布 {int(s["live"].sum())} 次）。已結算的 {len(settled)} 次中，'
        f'有 {int((excess > 0).sum())} 次贏同期大盤，平均每次 {pct(excess.mean())}。</p>'
        if len(settled) else ""
    )
    rows = []
    for _, r in s.iloc[::-1].iterrows():
        slug = str(r["period"])
        source = f'<a href="../archive/{slug}.html">實際發布</a>' if r["live"] else '<span class="muted">回測</span>'
        status = '<span class="chip new">持有中</span>' if r["ongoing"] else ""
        diff = r["ret"] - r["market_ret"]
        rows.append(
            f'<tr><th scope="row" class="num">{slug}</th><td>{source} {status}</td>'
            f'<td class="num">{r["entry"]:%Y-%m-%d}</td>'
            f'<td class="num {tone(r["yoy_3"])}">{pct(r["yoy_3"])}</td>'
            f'<td class="num {tone(r["ret"])}">{pct(r["ret"])}</td>'
            f'<td class="num {tone(r["market_ret"])}">{pct(r["market_ret"])}</td>'
            f'<td class="num diff-col {tone(diff)}">{pct(diff)}</td></tr>'
        )
    return summary + (
        '<div class="sheet scroll"><table><thead><tr><th>營收月份</th><th>來源</th><th class="num">進場</th>'
        '<th class="num">近三月<br>營收年增</th><th class="num">持有期間<br>報酬</th><th class="num">同期大盤</th>'
        f'<th class="num diff-col">差距</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def _reviews(p: StockProfile) -> str:
    if not p.reviews:
        return ""
    items = "".join(
        f'<li><b>{escape(r["period"])}</b> {severity_chip(r["severity"])} {escape(r["summary"])}</li>' for r in reversed(p.reviews)
    )
    return (
        '<section aria-labelledby="rv-h"><h2 id="rv-h">新聞與重大訊息檢查紀錄</h2>'
        f'<ul class="notes" style="list-style:none;padding:0">{items}</ul></section>'
    )


def render_stock_page(p: StockProfile) -> str:
    latest = p.latest
    facts = ""
    if latest is not None:
        facts = (
            '<div class="tally">'
            f'<div><span class="n {tone(latest["yoy_1"])}">{pct(latest["yoy_1"])}</span><span class="k">單月營收年增</span></div>'
            f'<div><span class="n {tone(latest["yoy_3"])}">{pct(latest["yoy_3"])}</span><span class="k">近三月營收年增</span></div>'
            f'<div><span class="n">{latest["rev_3m"] / 1e5:,.1f}</span><span class="k">近三月營收（億元）</span></div>'
            "</div>"
        )
    chip = '<span class="chip new">本月入選</span>' if p.picked else '<span class="chip">本月未入選</span>'
    close = f"{p.close:,.2f} 元" if pd.notna(p.close) else "—"
    return (
        _head(f"{p.code} {p.name}")
        + '<div class="wrap"><!--SITE_NAV-->'
        f'<header class="cover"><div><div class="eyebrow">個股查詢 · {escape(p.industry)}</div>'
        f'<h1><span class="code">{escape(p.code)}</span> {escape(p.name)}</h1></div>'
        f'<div class="cover-meta"><span>收盤價 <b>{close}</b></span><span>股價資料至 <b>{p.as_of:%Y-%m-%d}</b></span>'
        f"<span>營收月份 <b>{p.period}</b></span></div></header>"
        f'<section aria-labelledby="st-h"><div class="section-head"><h2 id="st-h">本月：{chip}</h2>'
        f"<p>{_status_sentence(p)}</p></div>{facts}<div class=\"sheet scroll\">{_checks_table(p)}</div></section>"
        f'<section aria-labelledby="rev-h"><div class="section-head"><h2 id="rev-h">月營收</h2>'
        f'<p class="muted">近 3 年，單位億元。</p></div><div class="sheet">{_revenue_chart(p)}</div></section>'
        f'<section aria-labelledby="sel-h"><div class="section-head"><h2 id="sel-h">入選紀錄</h2></div>{_selections(p)}</section>'
        f"{_reviews(p)}"
        f"{FOOTER}</div>"
    )


# ---------- 總表 ----------

def render_index(profiles: list[StockProfile]) -> str:
    def sort_key(p: StockProfile):
        return (not p.picked, -len(p.selections), p.code)

    rows = []
    for p in sorted(profiles, key=sort_key):
        latest_pick = str(p.selections["period"].iloc[-1]) if len(p.selections) else "—"
        yoy3 = p.latest["yoy_3"] if p.latest is not None else float("nan")
        key = escape(f"{p.code} {p.name} {p.industry}".lower(), quote=True)
        rows.append(
            f'<tr data-code="{escape(p.code, quote=True)}" data-key="{key}">'
            f'<th scope="row"><a href="{escape(p.code, quote=True)}.html"><span class="code">{escape(p.code)}</span> {escape(p.name)}</a></th>'
            f'<td class="muted">{escape(p.industry)}</td>'
            f'<td>{"<span class=\"chip new\">入選</span>" if p.picked else ""}</td>'
            f'<td class="num">{len(p.selections) or ""}</td><td class="num">{latest_pick}</td>'
            f'<td class="num {tone(yoy3)}">{pct(yoy3)}</td></tr>'
        )
    period = profiles[0].period if profiles else ""
    return (
        _head("個股查詢")
        + '<div class="wrap"><!--SITE_NAV-->'
        '<header class="cover"><div><div class="eyebrow">個股查詢</div><h1>這檔股票入選過嗎？</h1></div></header>'
        '<section aria-labelledby="q-h"><div class="section-head"><h2 id="q-h">搜尋</h2>'
        f'<p class="muted">輸入代號、名稱或產業。每檔都有 {period} 營收月份的條件檢查、近 3 年月營收，以及 2014 年以來的入選紀錄。</p></div>'
        '<div class="search"><label for="q" class="k">代號或名稱</label>'
        '<input id="q" type="search" placeholder="例如 2330、台積電、半導體" autocomplete="off" enterkeyhint="go">'
        f'<span class="muted">顯示 <b id="count">{len(profiles)}</b> 檔</span></div>'
        '<div class="sheet scroll"><table id="stocks"><thead><tr><th>股票</th><th>產業</th><th>本月</th>'
        '<th class="num">入選<br>次數</th><th class="num">最近<br>入選</th><th class="num">近三月<br>營收年增</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
        f"{FOOTER}</div>"
        f"<script>{SEARCH_SCRIPT}</script>"
    )
