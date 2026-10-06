"""SEC EDGAR XBRL 財報：代號 → CIK、抓 companyfacts、萃取營收原始數據並快取。

SEC 規定請求要附聯絡 email（.env 的 SEC_CONTACT_EMAIL），每秒不超過 10 次。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from quant_bot.common.http import REQUEST_TIMEOUT_SEC

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
REQUEST_DELAY_SEC = 0.35  # 約每秒 3 次，遠低於 SEC 上限
MAX_RETRIES = 4

# 依優先順序：公司常在不同年份換用不同標籤（例如 2018 年 ASC 606 之後）
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "RevenuesNetOfInterestExpense",
)
# 其他指標：毛利、營業成本（期間數字）、總資產（時點數字，沒有 start）
METRIC_TAGS = {
    "revenue": REVENUE_TAGS,
    "gross_profit": ("GrossProfit",),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "assets": ("Assets",),
}
ROW_COLUMNS = ["metric", "tag", "start", "end", "val", "filed", "form"]


class SecClient:
    def __init__(self, contact_email: str):
        if "@" not in contact_email:
            raise ValueError("SEC 需要聯絡 email：請在 .env 設定 SEC_CONTACT_EMAIL")
        self._headers = {"User-Agent": f"quant-bot research {contact_email}", "Accept-Encoding": "gzip, deflate"}

    def get_json(self, url: str) -> dict | None:
        """回傳 JSON；404（該公司沒有 XBRL 資料）回傳 None。"""
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, headers=self._headers, timeout=REQUEST_TIMEOUT_SEC)
                time.sleep(REQUEST_DELAY_SEC)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = 5 * 2**attempt
                log.warning("SEC retry %d in %ds: %s", attempt + 1, wait, exc.__class__.__name__)
                time.sleep(wait)
        raise AssertionError("unreachable")


def parse_ticker_map(payload: dict) -> dict[str, int]:
    """company_tickers.json -> {ticker: cik}（只有目前仍在申報的公司）。"""
    return {str(row["ticker"]).upper().replace(".", "-"): int(row["cik_str"]) for row in payload.values()}


def load_ticker_map(client: SecClient, cache: Path, refresh: bool = False) -> dict[str, int]:
    if refresh or not cache.exists():
        payload = client.get_json(TICKERS_URL)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")
    return parse_ticker_map(json.loads(cache.read_text(encoding="utf-8")))


def extract_rows(facts: dict) -> pd.DataFrame:
    """從 companyfacts 取出 METRIC_TAGS 的原始數據（美元）。時點數字（資產）的 start 為 NaT。"""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    rows = []
    for metric, tags in METRIC_TAGS.items():
        for tag in tags:
            for item in gaap.get(tag, {}).get("units", {}).get("USD", []):
                if not item.get("form", "").startswith(("10-Q", "10-K")):
                    continue
                if metric != "assets" and "start" not in item:
                    continue
                rows.append({"metric": metric, "tag": tag, "start": item.get("start"),
                             **{k: item[k] for k in ("end", "val", "filed", "form")}})
    df = pd.DataFrame(rows, columns=ROW_COLUMNS)
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    return df.astype({"val": float})


def extract_revenue_rows(facts: dict) -> pd.DataFrame:
    rows = extract_rows(facts)
    return rows[rows["metric"] == "revenue"].drop(columns="metric").reset_index(drop=True)


def fetch_rows(client: SecClient, cik: int, cache_dir: Path, refresh: bool = False) -> pd.DataFrame:
    """抓單一公司財報指標並快取成 parquet（只存萃取後的列，不存整份 companyfacts）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cik:010d}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    facts = client.get_json(FACTS_URL.format(cik=cik))
    rows = extract_rows(facts) if facts else pd.DataFrame(columns=ROW_COLUMNS)
    rows.to_parquet(path)
    return rows
