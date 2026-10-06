"""證交所「發行量加權股價報酬指數」（含息的大盤）：抓取、解析、快取。

一般看到的加權指數（^TWII）不含現金股利，台股每年配息約 3–4%，
拿它當基準會讓策略看起來多贏一截，所以這裡用報酬指數。
資料來源：https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U?date=YYYYMMDD&response=json（每次回傳一個月）
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from quant_bot.common.http import get_with_retry
from quant_bot.tw.mops import ROC_OFFSET

log = logging.getLogger(__name__)

URL_TEMPLATE = "https://www.twse.com.tw/rwd/zh/TAIEX/MFI94U?date={year}{month:02d}01&response=json"
REQUEST_DELAY_SEC = 3.0  # 證交所對頻繁請求會暫時封鎖


def parse_month_json(payload: dict) -> pd.Series:
    """把一個月的回傳轉成以日期為索引的指數序列。"""
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE returned stat={payload.get('stat')!r}")
    values = {}
    for roc_date, raw in payload.get("data", []):
        year, month, day = (int(x) for x in roc_date.split("/"))
        values[pd.Timestamp(year + ROC_OFFSET, month, day)] = float(raw.replace(",", ""))
    if not values:
        raise ValueError("no index data in payload")
    return pd.Series(values, name="taiex_tr").sort_index()


def fetch_month(period: pd.Period, cache_dir: Path, today: pd.Timestamp) -> pd.Series:
    """抓單月資料。已結束的月份會快取；當月每次都重抓（還在增加新的交易日）。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{period}.json"
    is_complete = period < today.to_period("M")
    if is_complete and path.exists():
        return parse_month_json(json.loads(path.read_text(encoding="utf-8")))

    resp = get_with_retry(URL_TEMPLATE.format(year=period.year, month=period.month))
    payload = resp.json()
    series = parse_month_json(payload)
    if is_complete:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    time.sleep(REQUEST_DELAY_SEC)
    return series


def load_total_return_index(start: str, cache_dir: Path, today: pd.Timestamp) -> pd.Series:
    periods = pd.period_range(start, today.to_period("M"), freq="M")
    parts = [fetch_month(p, cache_dir, today) for p in periods]
    return pd.concat(parts).sort_index()
