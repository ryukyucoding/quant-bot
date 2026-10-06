"""目標權重式投資組合回測：在指定日的收盤價調整到目標權重，其餘日子權重隨價格漂移。

假設：
- 以調整後收盤價（含除權息）計算報酬。
- 調倉在當日收盤成交，成本依 CostModel 從淨值扣除。
- 未配置的權重視為現金，報酬為 0。
- 停止交易的股票以最後價格持有（報酬 0）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_bot.common.costs import CostModel


@dataclass(frozen=True)
class BacktestResult:
    equity: pd.Series  # 每日淨值，起始為 1
    turnover: pd.Series  # 每次調倉的單邊周轉率（買進比例）
    costs: pd.Series  # 每次調倉的成本（佔淨值比例）
    holdings: Mapping[pd.Timestamp, pd.Series]  # 每次調倉後的目標權重

    @property
    def returns(self) -> pd.Series:
        return self.equity.pct_change().fillna(0.0)


def _validate_targets(targets: Mapping[pd.Timestamp, pd.Series], columns: pd.Index) -> None:
    for date, weights in targets.items():
        if (weights < -1e-12).any():
            raise ValueError(f"negative weight on {date:%Y-%m-%d} (long-only engine)")
        if weights.sum() > 1 + 1e-9:
            raise ValueError(f"weights sum > 1 on {date:%Y-%m-%d}")
        unknown = weights.index.difference(columns)
        if len(unknown):
            raise ValueError(f"no price data for {list(unknown)[:5]} on {date:%Y-%m-%d}")


def run_backtest(
    prices: pd.DataFrame,
    targets: Mapping[pd.Timestamp, pd.Series],
    costs: CostModel,
) -> BacktestResult:
    if not targets:
        raise ValueError("targets is empty")
    _validate_targets(targets, prices.columns)

    start = min(targets)
    px = prices.loc[prices.index >= start].ffill()
    daily_ret = px.pct_change().fillna(0.0).to_numpy()
    dates = px.index

    weights = np.zeros(px.shape[1])
    equity = np.empty(len(dates))
    nav = 1.0
    turnover: dict[pd.Timestamp, float] = {}
    paid: dict[pd.Timestamp, float] = {}
    holdings: dict[pd.Timestamp, pd.Series] = {}

    for i, date in enumerate(dates):
        if i > 0:
            gross = weights * (1.0 + daily_ret[i])
            port_ret = gross.sum() - weights.sum()
            nav *= 1.0 + port_ret
            weights = gross / (1.0 + port_ret)

        target = targets.get(date)
        if target is not None:
            target_arr = target.reindex(px.columns).fillna(0.0).to_numpy()
            delta = target_arr - weights
            bought = float(delta.clip(min=0).sum())
            sold = float((-delta).clip(min=0).sum())
            cost = costs.cost_of(bought, sold)
            nav *= 1.0 - cost
            weights = target_arr
            turnover[date] = bought
            paid[date] = cost
            holdings[date] = target[target > 0]

        equity[i] = nav

    return BacktestResult(
        equity=pd.Series(equity, index=dates, name="equity"),
        turnover=pd.Series(turnover, name="turnover"),
        costs=pd.Series(paid, name="costs"),
        holdings=holdings,
    )


def buy_and_hold(prices: pd.Series, start: pd.Timestamp) -> pd.Series:
    """單一標的買進持有的淨值曲線（起始為 1）。"""
    px = prices.loc[prices.index >= start].ffill().dropna()
    return (px / px.iloc[0]).rename("equity")
