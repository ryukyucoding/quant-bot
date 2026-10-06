"""美股季營收選股：S&P 500 當時的成分股中，依最新一季營收年增率排序，每月等權重持有前 N 檔。

規則在看回測結果之前就先定好，與台股版同一套邏輯，只是把月營收換成季營收。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_bot.common.prices import PricePanel
from quant_bot.us.fundamentals import features_as_of
from quant_bot.us.universe import members_on

EXECUTION_LAG_DAYS = 1  # 月初第一個交易日收盤後選股，隔一個交易日收盤成交


@dataclass(frozen=True)
class USStrategyConfig:
    name: str
    top_n: int = 20
    min_price: float = 5.0
    require_ttm_high: bool = False  # TTM 營收創近 8 季新高
    require_yoy_streak: bool = False  # 最近兩季營收都年增
    trend_window: int | None = None  # 股價需站上 N 日均線
    rank_by_growth: bool = True  # False = 成分股全部等權重（基準用）


def rebalance_dates(trading_days: pd.DatetimeIndex, start: pd.Timestamp) -> list[pd.Timestamp]:
    """每月第一個交易日。"""
    firsts = pd.Series(trading_days, index=trading_days).groupby(trading_days.to_period("M")).first()
    return [d for d in firsts if d >= start]


def eligible(
    quarters: pd.DataFrame,
    panel: PricePanel,
    history: pd.Series,
    date: pd.Timestamp,
    config: USStrategyConfig,
) -> pd.DataFrame:
    """回傳 date 當天合格的股票與其最新已申報季資料（index = ticker）。"""
    members = members_on(history, date)
    has_price = panel.adj_close.loc[date].dropna().index
    price = panel.close.loc[:date].iloc[-1]
    universe = [t for t in has_price if t in members and price.get(t, 0) >= config.min_price]

    if not config.rank_by_growth:
        return pd.DataFrame(index=pd.Index(universe, name="ticker"))

    feats = features_as_of(quarters, date)
    df = feats[feats.index.isin(universe)].dropna(subset=["yoy"])
    if config.require_ttm_high:
        df = df[df["ttm_high"]]
    if config.require_yoy_streak:
        df = df[(df["yoy"] > 0) & (df["yoy_prev"] > 0)]
    if config.trend_window:
        history_px = panel.adj_close.loc[:date].tail(config.trend_window)
        above = history_px.iloc[-1] > history_px.mean()
        df = df[above.reindex(df.index).fillna(False)]
    return df


def pick(candidates: pd.DataFrame, config: USStrategyConfig) -> pd.Series:
    if len(candidates) == 0:
        return pd.Series(dtype=float)
    if config.rank_by_growth:
        chosen = candidates.sort_values("yoy", ascending=False).head(config.top_n).index
    else:
        chosen = candidates.index
    return pd.Series(1.0 / len(chosen), index=chosen)


def build_targets(
    quarters: pd.DataFrame,
    panel: PricePanel,
    history: pd.Series,
    config: USStrategyConfig,
    start: pd.Timestamp,
) -> dict[pd.Timestamp, pd.Series]:
    days = panel.adj_close.index
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in rebalance_dates(days, start):
        position = days.get_loc(date) + EXECUTION_LAG_DAYS
        if position >= len(days):
            continue
        targets[days[position]] = pick(eligible(quarters, panel, history, date, config), config)
    return targets
