"""月營收選股策略：依營收成長排序，每月等權重持有前 N 檔。

規則在看回測結果之前就先定好，避免「調參調到歷史最漂亮」。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_bot.tw.factors import availability_date
from quant_bot.tw.prices import PricePanel

LIQUIDITY_WINDOW = 60  # 日
EXECUTION_LAG_DAYS = 1  # 用 D 日收盤資料決定，D+1 日收盤成交（避免用同一根收盤價決策又成交）
EXCLUDED_INDUSTRIES = ("金融保險業", "金融業", "存託憑證")  # 營收定義與一般公司不同


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    top_n: int = 20
    min_traded_value: float = 30_000_000  # 近 60 日平均成交金額（元）
    min_price: float = 10.0
    min_rev_3m: float = 300_000  # 近三月營收合計（千元）= 3 億
    require_12m_high: bool = False
    require_yoy_streak: bool = False
    trend_window: int | None = None  # 股價需站上 N 日均線
    rank_by_growth: bool = True  # False = 合格股票全部等權重（基準用）


def eligible_codes(
    features: pd.DataFrame,
    panel: PricePanel,
    traded_value: pd.DataFrame,
    date: pd.Timestamp,
    config: StrategyConfig,
    industries: pd.Series,
) -> pd.DataFrame:
    """回傳在 date 當天符合篩選條件的股票及其因子（尚未排序）。"""
    df = features[features.index.isin(panel.adj_close.columns)]
    df = df[~industries.reindex(df.index).isin(EXCLUDED_INDUSTRIES)]
    df = df[(df["rev_3m"] >= config.min_rev_3m) & (df["rev_3m_last_year"] >= config.min_rev_3m / 2)]

    price = panel.close.loc[:date].iloc[-1]
    value = traded_value.loc[:date].iloc[-1]
    has_price_today = panel.adj_close.loc[date].notna()
    df = df[
        price.reindex(df.index).ge(config.min_price)
        & value.reindex(df.index).ge(config.min_traded_value)
        & has_price_today.reindex(df.index).fillna(False)
    ]

    if config.require_12m_high:
        df = df[df["is_12m_high"]]
    if config.require_yoy_streak:
        df = df[df["yoy_streak"]]
    if config.trend_window:
        ma = panel.adj_close.loc[:date].tail(config.trend_window).mean()
        last = panel.adj_close.loc[:date].iloc[-1]
        df = df[(last > ma).reindex(df.index).fillna(False)]
    return df


def pick(eligible: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    """從合格股票中選股，回傳等權重 Series（index = code）。"""
    if eligible.empty:
        return pd.Series(dtype=float)
    if config.rank_by_growth:
        chosen = eligible.sort_values("yoy_3", ascending=False).head(config.top_n).index
    else:
        chosen = eligible.index
    return pd.Series(1.0 / len(chosen), index=chosen)


def build_targets(
    features: pd.DataFrame,
    panel: PricePanel,
    industries: pd.Series,
    config: StrategyConfig,
    start: pd.Timestamp,
) -> dict[pd.Timestamp, pd.Series]:
    """營收公布後第一個交易日 D 依收盤資料選股，目標權重掛在 D+EXECUTION_LAG_DAYS（成交日）。"""
    trading_days = panel.adj_close.index
    traded_value = panel.traded_value(LIQUIDITY_WINDOW)
    targets: dict[pd.Timestamp, pd.Series] = {}
    for period, period_features in features.groupby(level="period"):
        date = availability_date(period, trading_days)
        if date is None or date < start:
            continue
        position = trading_days.get_loc(date) + EXECUTION_LAG_DAYS
        if position >= len(trading_days):
            continue
        current = period_features.droplevel("period")
        eligible = eligible_codes(current, panel, traded_value, date, config, industries)
        targets[trading_days[position]] = pick(eligible, config)
    return targets
