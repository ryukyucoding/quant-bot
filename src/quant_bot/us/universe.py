"""S&P 500 歷史成分股（point-in-time），避免只拿「現在的成分股」回測造成倖存者偏差。

資料來源：github.com/fja05680/sp500（MIT 授權），每次成分股變動一列。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_bot.common.http import get_with_retry

HISTORY_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/"
    "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
)


def normalize_ticker(ticker: str) -> str:
    """統一成 Yahoo / SEC 的寫法：BRK.B -> BRK-B。"""
    return ticker.strip().upper().replace(".", "-")


def parse_history(csv_text: str) -> pd.Series:
    """回傳以變動日為索引、值為成分股 frozenset 的 Series。"""
    import io

    df = pd.read_csv(io.StringIO(csv_text), parse_dates=["date"])
    members = df["tickers"].map(lambda s: frozenset(normalize_ticker(t) for t in s.split(",") if t.strip()))
    return pd.Series(members.to_list(), index=pd.DatetimeIndex(df["date"]), name="members").sort_index()


def load_history(cache: Path, refresh: bool = False) -> pd.Series:
    if refresh or not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(get_with_retry(HISTORY_URL).text, encoding="utf-8")
    return parse_history(cache.read_text(encoding="utf-8"))


def members_on(history: pd.Series, date: pd.Timestamp) -> frozenset[str]:
    """date 當天（含）有效的成分股；早於第一筆紀錄則回傳空集合。"""
    known = history.loc[:date]
    return known.iloc[-1] if len(known) else frozenset()


def tickers_since(history: pd.Series, start: pd.Timestamp) -> set[str]:
    """start 之後任何時間曾是成分股的代號（含 start 當下的成分股）。"""
    window = history.loc[start:]
    union: set[str] = set(members_on(history, start))
    for members in window:
        union |= members
    return union
