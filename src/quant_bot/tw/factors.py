"""月營收因子。輸入為 MOPS 長表，輸出以 (period, code) 為索引的因子表。

公布規則：第 M 月營收須於 M+1 月 10 日前申報，所以第 M 月的因子
最早只能在「M+1 月 10 日之後的第一個交易日」使用，避免偷看未來。
"""

from __future__ import annotations

import pandas as pd

PUBLISH_DEADLINE_DAY = 10
YOY_LAG = 12


def revenue_wide(revenue: pd.DataFrame) -> pd.DataFrame:
    """period × code 的營收寬表（千元）。同月重複代號取最大值（轉板當月可能重複）。"""
    df = revenue.assign(period=pd.PeriodIndex(revenue["period"].astype(str), freq="M"))
    wide = df.pivot_table(index="period", columns="code", values="revenue", aggfunc="max")
    full_index = pd.period_range(wide.index.min(), wide.index.max(), freq="M")
    return wide.reindex(full_index)


def compute_features(wide: pd.DataFrame) -> pd.DataFrame:
    """回傳長表：period, code, revenue, yoy_1, yoy_3, rev_3m, rev_3m_last_year, is_12m_high, yoy_streak。"""
    rev_3m = wide.rolling(3, min_periods=3).sum()
    rev_3m_ly = rev_3m.shift(YOY_LAG)
    yoy_1 = wide / wide.shift(YOY_LAG) - 1
    features = {
        "revenue": wide,
        "yoy_1": yoy_1,
        "yoy_3": rev_3m / rev_3m_ly - 1,
        "rev_3m": rev_3m,
        "rev_3m_last_year": rev_3m_ly,
        "is_12m_high": wide >= wide.rolling(12, min_periods=12).max(),
        "yoy_streak": (yoy_1 > 0).astype(int).rolling(3, min_periods=3).sum() == 3,
    }
    stacked = {name: frame.stack(future_stack=True) for name, frame in features.items()}
    long = pd.DataFrame(stacked)
    long.index.names = ["period", "code"]
    long = long.dropna(subset=["revenue"])
    long["is_12m_high"] = long["is_12m_high"].astype(bool)
    long["yoy_streak"] = long["yoy_streak"].astype(bool)
    return long


def availability_date(period: pd.Period, trading_days: pd.DatetimeIndex) -> pd.Timestamp | None:
    """第 period 月營收可用的第一個交易日；資料範圍內不存在則回傳 None。"""
    next_month = period + 1
    cutoff = pd.Timestamp(year=next_month.year, month=next_month.month, day=PUBLISH_DEADLINE_DAY)
    candidates = trading_days[trading_days > cutoff]
    return candidates[0] if len(candidates) else None


def latest_published_period(today: pd.Timestamp) -> pd.Period:
    """申報期限已過（全體公司都應已公布）的最新月份。"""
    this_month = today.to_period("M")
    return this_month - 1 if today.day > PUBLISH_DEADLINE_DAY else this_month - 2
