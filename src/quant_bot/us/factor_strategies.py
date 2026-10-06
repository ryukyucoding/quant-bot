"""美股因子策略（規則見 docs/us_strategies_preregistration.md，回測前寫定）。

A 大盤趨勢濾網　B 價格動能　C 獲利品質　D 低波動　E 動能＋品質＋趨勢
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from quant_bot.common.prices import PricePanel
from quant_bot.us.fundamentals import features_as_of
from quant_bot.us.strategy import EXECUTION_LAG_DAYS, rebalance_dates
from quant_bot.us.universe import members_on

MARKET, CASH = "SPY", "BIL"
TREND_MONTHS = 10
MOMENTUM_LOOKBACK, MOMENTUM_SKIP = 252, 21
VOL_WINDOW, VOL_MIN_OBS = 252, 200


@dataclass(frozen=True)
class FactorConfig:
    name: str
    kind: str  # trend / momentum / quality / lowvol / combo
    top_n: int = 30


@dataclass(frozen=True)
class FactorInputs:
    panel: PricePanel
    history: pd.Series
    quality: pd.DataFrame  # ticker, end, filed, gpa


# ---------- 訊號 ----------

def trend_is_up(prices: pd.Series, date: pd.Timestamp) -> bool:
    """date 之前的月底收盤 > 最近 TREND_MONTHS 個月底收盤平均。資料不足時視為多頭（持有大盤）。"""
    px = prices.loc[: date - pd.Timedelta(days=1)].dropna()
    month_ends = px.groupby(px.index.to_period("M")).last()
    if px.index[-1].to_period("M") == date.to_period("M"):
        month_ends = month_ends.iloc[:-1]  # 本月還沒結束，不算月底
    if len(month_ends) < TREND_MONTHS:
        return True
    window = month_ends.iloc[-TREND_MONTHS:]
    return bool(window.iloc[-1] > window.mean())


def momentum_12_1(adj: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    px = adj.loc[:date]
    if len(px) <= MOMENTUM_LOOKBACK:
        return pd.Series(dtype=float)
    return (px.iloc[-1 - MOMENTUM_SKIP] / px.iloc[-1 - MOMENTUM_LOOKBACK] - 1).dropna()


def volatility(adj: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    returns = adj.loc[:date].tail(VOL_WINDOW + 1).pct_change(fill_method=None)
    counts = returns.notna().sum()
    return returns.std()[counts >= VOL_MIN_OBS]


def _universe(inputs: FactorInputs, date: pd.Timestamp) -> list[str]:
    members = members_on(inputs.history, date)
    priced = inputs.panel.adj_close.loc[date].dropna().index
    return [t for t in priced if t in members]


def _equal_weight(tickers) -> pd.Series:
    tickers = list(tickers)
    return pd.Series(1.0 / len(tickers), index=tickers) if tickers else pd.Series(dtype=float)


def _top(scores: pd.Series, universe: list[str], n: int, ascending: bool = False) -> pd.Series:
    ranked = scores.reindex(universe).dropna().sort_values(ascending=ascending)
    return _equal_weight(ranked.head(n).index)


# ---------- 各策略在決策日的目標權重 ----------

def weights_trend(inputs: FactorInputs, date: pd.Timestamp, config: FactorConfig) -> pd.Series:
    up = trend_is_up(inputs.panel.adj_close[MARKET], date)
    return pd.Series({MARKET if up else CASH: 1.0})


def weights_momentum(inputs: FactorInputs, date: pd.Timestamp, config: FactorConfig) -> pd.Series:
    return _top(momentum_12_1(inputs.panel.adj_close, date), _universe(inputs, date), config.top_n)


def weights_quality(inputs: FactorInputs, date: pd.Timestamp, config: FactorConfig) -> pd.Series:
    gpa = features_as_of(inputs.quality, date)["gpa"] if len(inputs.quality) else pd.Series(dtype=float)
    return _top(gpa, _universe(inputs, date), config.top_n)


def weights_lowvol(inputs: FactorInputs, date: pd.Timestamp, config: FactorConfig) -> pd.Series:
    return _top(volatility(inputs.panel.adj_close, date), _universe(inputs, date), config.top_n, ascending=True)


def weights_combo(inputs: FactorInputs, date: pd.Timestamp, config: FactorConfig) -> pd.Series:
    if not trend_is_up(inputs.panel.adj_close[MARKET], date):
        return pd.Series({CASH: 1.0})
    mom = weights_momentum(inputs, date, config) * 0.5
    qual = weights_quality(inputs, date, config) * 0.5
    return mom.add(qual, fill_value=0.0)


WEIGHERS: dict[str, Callable[[FactorInputs, pd.Timestamp, FactorConfig], pd.Series]] = {
    "trend": weights_trend,
    "momentum": weights_momentum,
    "quality": weights_quality,
    "lowvol": weights_lowvol,
    "combo": weights_combo,
}

FACTOR_STRATEGIES = (
    FactorConfig("A 大盤趨勢濾網", "trend"),
    FactorConfig("B 價格動能 前 30", "momentum", top_n=30),
    FactorConfig("C 獲利品質 前 30", "quality", top_n=30),
    FactorConfig("D 低波動 前 50", "lowvol", top_n=50),
    FactorConfig("E 動能＋品質＋趨勢", "combo", top_n=30),
)


def build_factor_targets(inputs: FactorInputs, config: FactorConfig, start: pd.Timestamp) -> dict[pd.Timestamp, pd.Series]:
    days = inputs.panel.adj_close.index
    weigh = WEIGHERS[config.kind]
    targets: dict[pd.Timestamp, pd.Series] = {}
    for date in rebalance_dates(days, start):
        position = days.get_loc(date) + EXECUTION_LAG_DAYS
        if position < len(days):
            targets[days[position]] = weigh(inputs, date, config)
    return targets
