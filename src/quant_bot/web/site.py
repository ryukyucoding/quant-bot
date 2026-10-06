"""公開網站：多個市場的月報、歷史紀錄與封存頁。輸出純靜態 HTML，不含 JavaScript。

site/
  index.html, archive/…        台股（根目錄，維持既有網址）
  us/index.html, us/archive/…  美股
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

from quant_bot.web.archive import PublishedMonth
from quant_bot.web.report import STYLE, TEMPLATES
from quant_bot.web.spec import MarketSpec, pct, tone
from quant_bot.web.track_record import cumulative

ARCHIVE_TEMPLATE = TEMPLATES / "archive.html"
WRAP_MARKER = '<div class="wrap">'
SITE_MARKERS = ("<!--SITE_NAV-->", "<!--SITE_SUBSCRIBE-->", "<!--SITE_FOOTER-->")
def csp(script_hashes: tuple[str, ...] = ()) -> str:
    """預設不允許任何 JavaScript；需要的頁面以 sha256 雜湊個別允許。"""
    scripts = f"script-src {' '.join(repr(h) for h in script_hashes)}; " if script_hashes else ""
    return (
        "default-src 'none'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        f"font-src https://fonts.gstatic.com; img-src 'self' data:; {scripts}base-uri 'none'; form-action 'none'"
    )


@dataclass(frozen=True)
class SiteConfig:
    site_name: str
    description: str
    base_url: str = ""
    telegram_channel_url: str = ""
    github_url: str = ""

    @classmethod
    def load(cls, path: Path) -> SiteConfig:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: str(v) for k, v in data.items() if k in cls.__dataclass_fields__})

    def page_url(self, relative: str) -> str:
        return f"{self.base_url.rstrip('/')}/{relative}" if self.base_url else ""


@dataclass(frozen=True)
class Variant:
    """與正式名單並列追蹤的實驗名單。"""

    key: str
    label: str
    note: str
    record: pd.DataFrame


@dataclass(frozen=True)
class MarketPages:
    spec: MarketSpec
    latest_body: str
    published: list[PublishedMonth]
    published_dir: Path
    record: pd.DataFrame
    backtest: pd.DataFrame
    variant: Variant | None = None


@dataclass(frozen=True)
class ResearchPage:
    """沒有每月名單的研究結果頁（例如美股）。"""

    key: str
    label: str  # 導覽列文字
    site_dir: str
    body: str
    title: str


@dataclass(frozen=True)
class StockPages:
    """個股查詢：總表與每檔一頁（內容已經是含 <!--SITE_NAV--> 標記的頁面主體）。"""

    index_body: str
    pages: dict[str, str]  # 代號 -> 頁面主體
    script_hash: str
    site_dir: str = "stocks/"


@dataclass(frozen=True)
class NavEntry:
    key: str
    label: str
    site_dir: str


@dataclass(frozen=True)
class PageContext:
    """目前頁面的位置，用來產生相對連結。"""

    current: str  # 目前所在的導覽項目 key
    page: str  # latest / archive / research
    to_root: str  # 回到網站根目錄的相對路徑，例如 "../../"
    market: MarketSpec | None = None  # 市場頁才有：顯示「紀錄」連結與訂閱區塊


# ---------- 共用頁面元件 ----------

def nav_html(config: SiteConfig, entries: list[NavEntry], ctx: PageContext) -> str:
    links = [
        (f"{ctx.to_root}{e.site_dir}index.html", e.label, ctx.page != "archive" and e.key == ctx.current)
        for e in entries
    ]
    if ctx.market is not None:
        links.append((f"{ctx.to_root}{ctx.market.site_dir}archive/index.html", f"{ctx.market.label}紀錄", ctx.page == "archive"))
    links.append((f"{ctx.to_root}{entries[0].site_dir}index.html#subscribe", "訂閱推播", False))
    items = "".join(
        f'<li><a href="{href}"{" aria-current=page" if current else ""}>{label}</a></li>' for href, label, current in links
    )
    return (
        f'<nav class="site-nav" aria-label="網站導覽"><a class="site-name" href="{ctx.to_root}index.html">'
        f'{escape(config.site_name)}</a><ul class="site-links">{items}</ul></nav>'
    )


def subscribe_html(config: SiteConfig, spec: MarketSpec) -> str:
    if config.telegram_channel_url:
        action = f'<a class="button" href="{escape(config.telegram_channel_url)}" rel="noopener">加入 Telegram 頻道</a>'
        note = f"{spec.subscribe_note}：要買、要賣、續抱，附完整報告。免費，不用留任何資料，不想收隨時退出頻道。"
    else:
        action = '<span class="button disabled" aria-disabled="true">頻道準備中</span>'
        note = f"Telegram 頻道即將開放，{spec.subscribe_note}。"
    return (
        '<section class="subscribe" id="subscribe" aria-labelledby="sub-h">'
        f'<div><h2 id="sub-h">每月推播</h2><p>{escape(note)}</p></div>{action}</section>'
    )


def footer_html(config: SiteConfig) -> str:
    source = f' · <a href="{escape(config.github_url)}" rel="noopener">原始碼</a>' if config.github_url else ""
    return f"本站為個人研究，不是投資建議，也不提供付費服務{source}。<br>"


def finalize_page(
    body: str,
    config: SiteConfig,
    entries: list[NavEntry],
    ctx: PageContext,
    *,
    title: str,
    banner: str = "",
    script_hashes: tuple[str, ...] = (),
) -> str:
    """把頁面內容包成完整 HTML：<head> 放樣式與 meta，<body> 放內容並套上導覽。"""
    split = body.index(WRAP_MARKER)
    head_part, content = body[:split], body[split:]
    head_part = head_part.replace(head_part[head_part.index("<title>") : head_part.index("</title>") + 8], "")
    content = (
        content.replace("<!--SITE_NAV-->", nav_html(config, entries, ctx) + banner)
        .replace("<!--SITE_SUBSCRIBE-->", subscribe_html(config, ctx.market) if ctx.market else "")
        .replace("<!--SITE_FOOTER-->", footer_html(config))
    )
    description = escape(config.description)
    return (
        '<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp(script_hashes)}">\n'
        '<meta name="referrer" content="strict-origin-when-cross-origin">\n'
        f"<title>{escape(title)}</title>\n"
        f'<meta name="description" content="{description}">\n'
        f'<meta property="og:title" content="{escape(title)}">\n'
        f'<meta property="og:description" content="{description}">\n'
        '<meta property="og:type" content="website">\n'
        f"{head_part}</head>\n<body>\n{content}\n</body>\n</html>\n"
    )


def strip_site_markers(body: str) -> str:
    """單檔使用（Telegram 附件、本機檢視）時移除網站專用標記。"""
    for marker in SITE_MARKERS:
        body = body.replace(marker, "")
    return body


# ---------- 歷史紀錄頁 ----------

def _date(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{pd.Timestamp(value):%Y-%m-%d}"


def _track_head(spec: MarketSpec, variant: Variant | None) -> str:
    extra = f'<th class="num">{escape(variant.label)}</th>' if variant else ""
    return (
        f'<th>{escape(spec.period_header)}</th><th class="num">進場</th><th class="num">出場</th><th class="num">檔數</th>'
        f'<th class="num">名單報酬</th>{extra}<th class="num">大盤</th><th class="num diff-col">差距</th><th>狀態</th>'
    )


def _published_rows(record: pd.DataFrame, variant: Variant | None) -> str:
    if record.empty:
        return '<tr><td colspan="9" class="muted">還沒有發布紀錄。</td></tr>'
    variant_by_period = variant.record.set_index("period")["strategy"] if variant is not None and len(variant.record) else pd.Series(dtype=float)
    rows = []
    for _, r in record.iloc[::-1].iterrows():
        slug = str(r["period"])
        status = '<span class="chip new status">進行中</span>' if r["ongoing"] else '<span class="chip status">已結算</span>'
        extra = ""
        if variant is not None:
            v = variant_by_period.get(r["period"], float("nan"))
            extra = f'<td class="num {tone(v)}">{pct(v)}</td>'
        rows.append(
            "<tr>"
            f'<th scope="row"><a href="{slug}.html">{slug}</a></th>'
            f'<td class="num">{_date(r["entry"])}</td><td class="num">{_date(r["exit"])}</td>'
            f'<td class="num">{int(r["n"])}</td>'
            f'<td class="num {tone(r["strategy"])}">{pct(r["strategy"])}</td>{extra}'
            f'<td class="num {tone(r["market"])}">{pct(r["market"])}</td>'
            f'<td class="num diff-col {tone(r["excess"])}">{pct(r["excess"])}</td>'
            f"<td>{status}</td></tr>"
        )
    return "".join(rows)


def _backtest_rows(periods: pd.DataFrame) -> str:
    return "".join(
        "<tr>"
        f'<td class="num">{_date(r["entry"])}</td><td class="num">{_date(r["exit"])}</td>'
        f'<td class="num">{int(r["n"])}</td>'
        f'<td class="num {tone(r["strategy"])}">{pct(r["strategy"])}</td>'
        f'<td class="num {tone(r["market"])}">{pct(r["market"])}</td>'
        f'<td class="num diff-col {tone(r["excess"])}">{pct(r["excess"])}</td></tr>'
        for _, r in periods.iloc[::-1].iterrows()
    )


def _tally(frame: pd.DataFrame) -> dict[str, str]:
    settled = frame.dropna(subset=["strategy", "market"])
    if settled.empty:
        return {"cum_s": "—", "cum_m": "—", "won": "0", "total": "0", "tone": "flat"}
    cum_s, cum_m = cumulative(settled["strategy"]), cumulative(settled["market"])
    return {
        "cum_s": pct(cum_s),
        "cum_m": pct(cum_m),
        "won": str(int((settled["excess"] > 0).sum())),
        "total": str(len(settled)),
        "tone": tone(cum_s - cum_m),
    }


def _variant_card(variant: Variant | None) -> str:
    if variant is None:
        return ""
    tally = _tally(variant.record)
    return (
        f'<div class="vs"><span class="k">{escape(variant.label)}累積</span>'
        f'<span class="big num {tone_of(variant.record)}">{tally["cum_s"]}</span>'
        '<span class="detail">實驗名單，同樣等權重、未扣成本</span></div>'
    )


def tone_of(record: pd.DataFrame) -> str:
    settled = record.dropna(subset=["strategy"])
    return tone(cumulative(settled["strategy"])) if len(settled) else "flat"


def render_archive(spec: MarketSpec, record: pd.DataFrame, backtest: pd.DataFrame, variant: Variant | None = None) -> str:
    live, bt = _tally(record), _tally(backtest)
    lede = f"從 {record['period'].iloc[0]} 的名單開始公開發布。" if len(record) else spec.first_publish_note
    replacements = {
        "{{STYLE}}": STYLE.read_text(encoding="utf-8"),
        "{{EYEBROW}}": escape(f"{spec.name} · 紀錄"),
        "{{PERIOD_HEADER}}": escape(spec.period_header),
        "{{MARKET_NOTE}}": escape(spec.market_note),
        "{{SOURCES}}": escape(spec.sources),
        "{{TRACK_HEAD}}": _track_head(spec, variant),
        "{{PUBLISHED_ROWS}}": _published_rows(record, variant),
        "{{VARIANT_CARD}}": _variant_card(variant),
        "{{VARIANT_NOTE}}": escape(variant.note) if variant else "",
        "{{LIVE_CUM_S}}": live["cum_s"],
        "{{LIVE_CUM_M}}": live["cum_m"],
        "{{LIVE_WON}}": live["won"],
        "{{LIVE_TOTAL}}": live["total"],
        "{{LIVE_TONE}}": live["tone"],
        "{{LIVE_LEDE}}": escape(lede),
        "{{BT_ROWS}}": _backtest_rows(backtest),
        "{{BT_WON}}": bt["won"],
        "{{BT_TOTAL}}": bt["total"],
        "{{BT_FIRST}}": _date(backtest["entry"].iloc[0]) if len(backtest) else "—",
        "{{BT_LAST}}": _date(backtest["exit"].iloc[-1]) if len(backtest) else "—",
    }
    html = ARCHIVE_TEMPLATE.read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(key, value)
    return html


def archived_banner(month: PublishedMonth) -> str:
    return (
        '<p class="sheet" role="note" style="margin:0">這是 '
        f"<b>{month.published_at:%Y-%m-%d}</b> 發布的封存頁面，內容不再更新。"
        '<a href="../index.html">看本月最新名單 →</a></p>'
    )


# ---------- 建站 ----------

def _depth_prefix(site_dir: str, extra_levels: int) -> str:
    depth = len([p for p in site_dir.split("/") if p]) + extra_levels
    return "../" * depth


def build_market(out_dir: Path, config: SiteConfig, entries: list[NavEntry], pages: MarketPages) -> list[Path]:
    spec = pages.spec
    base = out_dir / spec.site_dir
    archive_dir = base / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    written = []

    index = base / "index.html"
    ctx = PageContext(spec.key, "latest", _depth_prefix(spec.site_dir, 0), spec)
    title = config.site_name if not spec.site_dir else f"{spec.name}｜{config.site_name}"
    index.write_text(finalize_page(pages.latest_body, config, entries, ctx, title=title), encoding="utf-8")
    written.append(index)

    archive_ctx = PageContext(spec.key, "archive", _depth_prefix(spec.site_dir, 1), spec)
    for month in pages.published:
        body = (pages.published_dir / f"{month.slug}.html").read_text(encoding="utf-8")
        page = archive_dir / f"{month.slug}.html"
        page.write_text(
            finalize_page(body, config, entries, archive_ctx, title=f"{spec.label} {month.slug} 名單｜{config.site_name}",
                          banner=archived_banner(month)),
            encoding="utf-8",
        )
        written.append(page)

    archive_index = archive_dir / "index.html"
    archive_index.write_text(
        finalize_page(render_archive(spec, pages.record, pages.backtest, pages.variant), config, entries, archive_ctx,
                      title=f"{spec.label}歷史紀錄｜{config.site_name}"),
        encoding="utf-8",
    )
    written.append(archive_index)
    return written


def build_research(out_dir: Path, config: SiteConfig, entries: list[NavEntry], page: ResearchPage) -> Path:
    path = out_dir / page.site_dir / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    ctx = PageContext(page.key, "research", _depth_prefix(page.site_dir, 0))
    path.write_text(finalize_page(page.body, config, entries, ctx, title=f"{page.title}｜{config.site_name}"), encoding="utf-8")
    return path


def build_stocks(out_dir: Path, config: SiteConfig, entries: list[NavEntry], stocks: StockPages) -> list[Path]:
    base = out_dir / stocks.site_dir
    base.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "site.css").write_text(STYLE.read_text(encoding="utf-8"), encoding="utf-8")
    ctx = PageContext("stocks", "research", _depth_prefix(stocks.site_dir, 0))
    index = base / "index.html"
    index.write_text(
        finalize_page(stocks.index_body, config, entries, ctx, title=f"個股查詢｜{config.site_name}",
                      script_hashes=(stocks.script_hash,)),
        encoding="utf-8",
    )
    written = [index]
    for code, body in stocks.pages.items():
        page = base / f"{code}.html"
        title = body[body.index("<title>") + 7 : body.index("</title>")]
        page.write_text(finalize_page(body, config, entries, ctx, title=f"{title}｜{config.site_name}"), encoding="utf-8")
        written.append(page)
    return written


def build_site(
    out_dir: Path,
    config: SiteConfig,
    markets: list[MarketPages],
    research: tuple[ResearchPage, ...] = (),
    stocks: StockPages | None = None,
) -> list[Path]:
    entries = [NavEntry(m.spec.key, f"{m.spec.label}名單", m.spec.site_dir) for m in markets]
    if stocks is not None:
        entries.append(NavEntry("stocks", "個股查詢", stocks.site_dir))
    entries += [NavEntry(r.key, r.label, r.site_dir) for r in research]
    written = [path for pages in markets for path in build_market(out_dir, config, entries, pages)]
    written += [build_research(out_dir, config, entries, page) for page in research]
    if stocks is not None:
        written += build_stocks(out_dir, config, entries, stocks)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages 不要跑 Jekyll
    return written
