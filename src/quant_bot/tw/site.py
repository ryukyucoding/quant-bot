"""公開網站：把月報包成完整頁面（導覽、訂閱、CSP），並產生歷史紀錄頁。輸出純靜態 HTML，不含 JavaScript。

site/
  index.html             本月名單（最新月報）
  archive/index.html     已發布名單的真實紀錄 + 回測逐期對照
  archive/YYYY-MM.html   每月發布時的封存頁
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

from quant_bot.tw.archive import PublishedMonth
from quant_bot.tw.report import STYLE, TEMPLATES, pct, tone
from quant_bot.tw.track_record import cumulative

ARCHIVE_TEMPLATE = TEMPLATES / "archive.html"
WRAP_MARKER = '<div class="wrap">'
CSP = (
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; base-uri 'none'; form-action 'none'"
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


# ---------- 共用頁面元件 ----------

def nav_html(config: SiteConfig, current: str, prefix: str) -> str:
    links = [("latest", "index.html", "本月名單"), ("archive", "archive/index.html", "歷史紀錄"), ("subscribe", "index.html#subscribe", "訂閱推播")]
    items = "".join(
        f'<li><a href="{prefix}{href}"{" aria-current=page" if key == current else ""}>{label}</a></li>'
        for key, href, label in links
    )
    return (
        f'<nav class="site-nav" aria-label="網站導覽"><a class="site-name" href="{prefix}index.html">'
        f'{escape(config.site_name)}</a><ul class="site-links">{items}</ul></nav>'
    )


def subscribe_html(config: SiteConfig) -> str:
    if config.telegram_channel_url:
        action = f'<a class="button" href="{escape(config.telegram_channel_url)}" rel="noopener">加入 Telegram 頻道</a>'
        note = "每月 11 日營收公布後推播：要買、要賣、續抱，附完整報告。免費，不用留任何資料，不想收隨時退出頻道。"
    else:
        action = '<span class="button disabled" aria-disabled="true">頻道準備中</span>'
        note = "Telegram 頻道即將開放，每月 11 日營收公布後推播名單。"
    return (
        '<section class="subscribe" id="subscribe" aria-labelledby="sub-h">'
        f'<div><h2 id="sub-h">每月推播</h2><p>{note}</p></div>{action}</section>'
    )


def footer_html(config: SiteConfig) -> str:
    source = f' · <a href="{escape(config.github_url)}" rel="noopener">原始碼</a>' if config.github_url else ""
    return f"本站為個人研究，不是投資建議，也不提供付費服務{source}。<br>"


def finalize_page(body: str, config: SiteConfig, *, current: str, prefix: str, title: str, banner: str = "") -> str:
    """把頁面內容包成完整 HTML：<head> 放樣式與 meta，<body> 放內容並套上導覽。"""
    split = body.index(WRAP_MARKER)
    head_part, content = body[:split], body[split:]
    head_part = head_part.replace(head_part[head_part.index("<title>") : head_part.index("</title>") + 8], "")
    content = (
        content.replace("<!--SITE_NAV-->", nav_html(config, current, prefix) + banner)
        .replace("<!--SITE_SUBSCRIBE-->", subscribe_html(config))
        .replace("<!--SITE_FOOTER-->", footer_html(config))
    )
    description = escape(config.description)
    return (
        '<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
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
    for marker in ("<!--SITE_NAV-->", "<!--SITE_SUBSCRIBE-->", "<!--SITE_FOOTER-->"):
        body = body.replace(marker, "")
    return body


# ---------- 歷史紀錄頁 ----------

def _date(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{pd.Timestamp(value):%Y-%m-%d}"


def _published_rows(record: pd.DataFrame) -> str:
    if record.empty:
        return '<tr><td colspan="8" class="muted">還沒有發布紀錄。</td></tr>'
    rows = []
    for _, r in record.iloc[::-1].iterrows():
        slug = str(r["period"])
        status = '<span class="chip new status">進行中</span>' if r["ongoing"] else '<span class="chip status">已結算</span>'
        rows.append(
            "<tr>"
            f'<th scope="row"><a href="{slug}.html">{slug}</a></th>'
            f'<td class="num">{_date(r["entry"])}</td><td class="num">{_date(r["exit"])}</td>'
            f'<td class="num">{int(r["n"])}</td>'
            f'<td class="num {tone(r["strategy"])}">{pct(r["strategy"])}</td>'
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


def render_archive(config: SiteConfig, record: pd.DataFrame, backtest: pd.DataFrame) -> str:
    live, bt = _tally(record), _tally(backtest)
    lede = (
        f"從 {record['period'].iloc[0]} 營收的名單開始公開發布。"
        if len(record)
        else "還沒有正式發布的名單，第一期會在下一次營收公布後（每月 11 日）發布。"
    )
    replacements = {
        "{{STYLE}}": STYLE.read_text(encoding="utf-8"),
        "{{PUBLISHED_ROWS}}": _published_rows(record),
        "{{LIVE_CUM_S}}": live["cum_s"],
        "{{LIVE_CUM_M}}": live["cum_m"],
        "{{LIVE_WON}}": live["won"],
        "{{LIVE_TOTAL}}": live["total"],
        "{{LIVE_TONE}}": live["tone"],
        "{{LIVE_LEDE}}": lede,
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

def build_site(
    out_dir: Path,
    config: SiteConfig,
    latest_body: str,
    published: list[PublishedMonth],
    published_dir: Path,
    record: pd.DataFrame,
    backtest: pd.DataFrame,
) -> list[Path]:
    archive_dir = out_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    written = []

    index = out_dir / "index.html"
    index.write_text(
        finalize_page(latest_body, config, current="latest", prefix="", title=config.site_name), encoding="utf-8"
    )
    written.append(index)

    for month in published:
        body = (published_dir / f"{month.slug}.html").read_text(encoding="utf-8")
        page = archive_dir / f"{month.slug}.html"
        page.write_text(
            finalize_page(
                body, config, current="archive", prefix="../",
                title=f"{month.slug} 名單｜{config.site_name}", banner=archived_banner(month),
            ),
            encoding="utf-8",
        )
        written.append(page)

    archive_index = archive_dir / "index.html"
    archive_index.write_text(
        finalize_page(
            render_archive(config, record, backtest), config, current="archive", prefix="../",
            title=f"歷史紀錄｜{config.site_name}",
        ),
        encoding="utf-8",
    )
    written.append(archive_index)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages 不要跑 Jekyll
    return written
