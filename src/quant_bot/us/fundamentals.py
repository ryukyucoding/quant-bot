"""季營收（point-in-time）與因子。

處理順序：
1. 同一個 (期間起, 期間迄) 可能出現在多份申報（後來的財報會重列去年數字）：
   保留「最早申報」的數字，也就是當時市場真正看到的數字。同一天申報的多個標籤依優先順序取一個。
2. 年報只有全年數字：Q4 = 全年 − 前三季累計（10-Q 第三季的 9 個月數字），申報日取年報日期。
3. 依季底排序計算因子；每個因子只用到「申報日 ≤ 該季申報日」的資料。
"""

from __future__ import annotations

import pandas as pd

from quant_bot.us.sec import REVENUE_TAGS

QUARTER_DAYS = (80, 100)
NINE_MONTH_DAYS = (260, 290)
YEAR_DAYS = (350, 380)
YOY_MATCH_DAYS = (350, 380)  # 去年同季的季底距離
TTM_HIGH_QUARTERS = 8  # TTM 營收創近 8 季新高
MAX_STALENESS_DAYS = 200  # 最新一季季底距今超過這麼久，視為資料過期



def _empty(name: str) -> pd.DataFrame:
    return pd.DataFrame({"end": pd.Series(dtype="datetime64[ns]"), "filed": pd.Series(dtype="datetime64[ns]"),
                         name: pd.Series(dtype=float)})


def _first_reported(rows: pd.DataFrame, tags: tuple[str, ...] = REVENUE_TAGS) -> pd.DataFrame:
    rank = {tag: i for i, tag in enumerate(tags)}
    ranked = rows.assign(rank=rows["tag"].map(rank).fillna(len(tags)))
    ranked = ranked.sort_values(["start", "end", "filed", "rank"])
    return ranked.drop_duplicates(["start", "end"], keep="first").drop(columns="rank")


def _duration(df: pd.DataFrame) -> pd.Series:
    return (df["end"] - df["start"]).dt.days


def quarterly_values(rows: pd.DataFrame, tags: tuple[str, ...], name: str) -> pd.DataFrame:
    """期間型指標（營收、毛利…）→ [end, filed, name]，每季一列；Q4 由全年減前三季推得。"""
    if rows.empty:
        return _empty(name)
    first = _first_reported(rows, tags)
    days = _duration(first)
    quarters = first[days.between(*QUARTER_DAYS)][["end", "filed", "val"]]

    years = first[days.between(*YEAR_DAYS)]
    nine = first[days.between(*NINE_MONTH_DAYS)].set_index("start")
    derived = []
    for _, fy in years.iterrows():
        if fy["start"] not in nine.index:
            continue
        ytd = nine.loc[[fy["start"]]].iloc[0]
        derived.append({"end": fy["end"], "filed": max(fy["filed"], ytd["filed"]), "val": fy["val"] - ytd["val"]})

    combined = pd.concat([quarters, pd.DataFrame(derived, columns=["end", "filed", "val"])], ignore_index=True)
    combined = combined.astype({"end": "datetime64[ns]", "filed": "datetime64[ns]", "val": float})
    combined = combined.sort_values(["end", "filed"]).drop_duplicates("end", keep="first")
    combined = combined[combined["val"] > 0]
    return combined.rename(columns={"val": name}).reset_index(drop=True)


def quarterly_revenue(rows: pd.DataFrame) -> pd.DataFrame:
    """回傳 [end, filed, revenue]，每季一列，依季底排序。"""
    return quarterly_values(rows, REVENUE_TAGS, "revenue")


def instant_values(rows: pd.DataFrame, name: str) -> pd.DataFrame:
    """時點型指標（總資產）→ [end, filed, name]，每個資產負債表日一列，取第一次申報的數字。"""
    if rows.empty:
        return _empty(name)
    first = rows.sort_values(["end", "filed"]).drop_duplicates("end", keep="first")
    first = first.astype({"end": "datetime64[ns]", "filed": "datetime64[ns]"})
    return first[["end", "filed", "val"]].rename(columns={"val": name}).reset_index(drop=True)


def _same_quarter_last_year(quarters: pd.DataFrame, end: pd.Timestamp) -> float:
    gap = (end - quarters["end"]).dt.days
    match = quarters[gap.between(*YOY_MATCH_DAYS)]
    return float(match["revenue"].iloc[-1]) if len(match) else float("nan")


def quarter_features(quarters: pd.DataFrame) -> pd.DataFrame:
    """每季加上 yoy、上一季 yoy、TTM、TTM 是否創近 8 季新高。"""
    if quarters.empty:
        return quarters.assign(yoy=[], yoy_prev=[], ttm=[], ttm_high=[])
    q = quarters.sort_values("end").reset_index(drop=True)
    last_year = [_same_quarter_last_year(q.iloc[:i], end) for i, end in enumerate(q["end"])]
    yoy = q["revenue"] / pd.Series(last_year) - 1
    # TTM 需要連續四季：季底間隔都在一季左右
    consecutive = q["end"].diff().dt.days.between(*QUARTER_DAYS).astype(int).rolling(3).sum() == 3
    ttm = q["revenue"].rolling(4).sum().where(consecutive)
    ttm_high = ttm >= ttm.rolling(TTM_HIGH_QUARTERS, min_periods=TTM_HIGH_QUARTERS).max()
    return q.assign(yoy=yoy, yoy_prev=yoy.shift(1), ttm=ttm, ttm_high=ttm_high.fillna(False).astype(bool))


def features_as_of(table: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """table: 全部公司的 quarter_features（含 ticker 欄）。回傳 date 前已申報的最新一季（每個 ticker 一列）。"""
    known = table[(table["filed"] < date) & ((date - table["end"]).dt.days <= MAX_STALENESS_DAYS)]
    latest = known.sort_values(["ticker", "end", "filed"]).groupby("ticker").tail(1)
    return latest.set_index("ticker")
