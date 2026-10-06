"""公開資訊觀測站 (MOPS) 月營收彙總表：抓取、解析、快取。

每個月一頁，包含該市場所有公司的當月營收，依產業分表。
資料來源：https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{民國年}_{月}_0.html
"""

from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path

import pandas as pd
import requests

from quant_bot.common.http import get_with_retry

log = logging.getLogger(__name__)

MARKETS = ("sii", "otc")  # sii = 上市, otc = 上櫃
URL_TEMPLATE = "https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{roc_year}_{month}_0.html"
REQUEST_DELAY_SEC = 1.5
ROC_OFFSET = 1911

_INDUSTRY_RE = re.compile(r"產業別：([^\s'\",)]+)")
_CODE_RE = re.compile(r"^\d{4}$")  # 只保留 4 碼普通股


def _normalize_industry(raw: str) -> str:
    """去掉括號說明，例如「金融保險業（其中金控公司…）」→「金融保險業」。"""
    return re.split(r"[（(]", raw.strip(), maxsplit=1)[0]


def month_url(year: int, month: int, market: str) -> str:
    if market not in MARKETS:
        raise ValueError(f"unknown market: {market}")
    return URL_TEMPLATE.format(market=market, roc_year=year - ROC_OFFSET, month=month)


def _to_number(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def parse_month_html(html: str, year: int, month: int, market: str) -> pd.DataFrame:
    """把一頁月營收彙總表解析成 tidy DataFrame（單位：千元）。"""
    tables = pd.read_html(io.StringIO(html))
    rows: list[pd.DataFrame] = []
    industry: str | None = None
    for table in tables:
        header = " ".join(str(c) for c in table.columns)
        match = _INDUSTRY_RE.search(header)
        if match:
            industry = _normalize_industry(match.group(1))
            continue
        if table.shape[1] < 10 or industry is None:
            continue
        flat = table.iloc[:, :10].copy()
        flat.columns = [
            "code", "name", "revenue", "rev_prev_month", "rev_last_year",
            "mom_pct", "yoy_pct", "cum_revenue", "cum_last_year", "cum_yoy_pct",
        ]
        flat = flat[flat["code"].astype(str).str.strip().str.match(_CODE_RE)]
        flat = flat.assign(code=flat["code"].astype(str).str.strip(), industry=industry)
        rows.append(flat)

    if not rows:
        raise ValueError(f"no revenue tables found for {market} {year}-{month:02d}")

    df = pd.concat(rows, ignore_index=True)
    numeric_cols = ["revenue", "rev_prev_month", "rev_last_year", "cum_revenue", "cum_last_year"]
    df = df.assign(**{c: _to_number(df[c]) for c in numeric_cols})
    df = df.assign(market=market, period=pd.Period(year=year, month=month, freq="M"))
    return df[["period", "market", "code", "name", "industry", *numeric_cols]]


def fetch_month_html(year: int, month: int, market: str, cache_dir: Path) -> str:
    """下載單月 HTML，已快取則直接讀檔。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{market}_{year}_{month:02d}.html"
    if path.exists():
        return path.read_text(encoding="utf-8")

    url = month_url(year, month, market)
    resp = get_with_retry(url)
    html = resp.content.decode("big5", errors="replace")
    if "營業收入" not in html:
        raise ValueError(f"unexpected page content: {url}")
    path.write_text(html, encoding="utf-8")
    time.sleep(REQUEST_DELAY_SEC)
    return html


def load_revenue(periods: pd.PeriodIndex, cache_dir: Path) -> pd.DataFrame:
    """抓取並合併多個月份、兩個市場的月營收。尚未公布的月份會略過並記錄。"""
    frames: list[pd.DataFrame] = []
    for period in periods:
        for market in MARKETS:
            try:
                html = fetch_month_html(period.year, period.month, market, cache_dir)
                frames.append(parse_month_html(html, period.year, period.month, market))
            except (requests.RequestException, ValueError) as exc:
                log.warning("skip %s %s: %s", market, period, exc)
    if not frames:
        raise RuntimeError("no revenue data loaded")
    return pd.concat(frames, ignore_index=True)
