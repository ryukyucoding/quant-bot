"""績效指標。所有函式輸入為淨值曲線（pd.Series，DatetimeIndex）。"""

from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365.25


def cagr(equity: pd.Series) -> float:
    years = (equity.index[-1] - equity.index[0]).days / DAYS_PER_YEAR
    if years <= 0:
        return 0.0
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def max_drawdown(equity: pd.Series) -> float:
    return float(drawdown(equity).min())


def annual_volatility(equity: pd.Series) -> float:
    return float(equity.pct_change().dropna().std() * math.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe(equity: pd.Series, risk_free: float = 0.0) -> float:
    """年化 Sharpe（以日報酬計算，無風險利率為年化值）。"""
    daily = equity.pct_change().dropna() - risk_free / TRADING_DAYS_PER_YEAR
    std = daily.std()
    if std == 0 or math.isnan(std):
        return 0.0
    return float(daily.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR))


def calendar_year_returns(equity: pd.Series) -> pd.Series:
    year_end = equity.groupby(equity.index.year).last()
    prev = year_end.shift(1)
    prev.iloc[0] = equity.iloc[0]
    return year_end / prev - 1


def summarize(equity: pd.Series) -> dict[str, float]:
    return {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "cagr": cagr(equity),
        "max_drawdown": max_drawdown(equity),
        "volatility": annual_volatility(equity),
        "sharpe": sharpe(equity),
    }


def relative_to(equity: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """策略相對基準：年化報酬差、完整年度中贏的年數。兩者先對齊到共同日期。"""
    common = equity.index.intersection(benchmark.index)
    strat, bench = equity.loc[common], benchmark.loc[common]
    yearly_diff = calendar_year_returns(strat) - calendar_year_returns(bench)
    complete = yearly_diff.iloc[1:-1] if len(yearly_diff) > 2 else yearly_diff.iloc[0:0]
    return {
        "excess_cagr": cagr(strat) - cagr(bench),
        "years_won": int((complete > 0).sum()),
        "years_total": int(len(complete)),
    }
