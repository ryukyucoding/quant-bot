"""各市場共用的結果型別：策略回測、基準、每月名單。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from quant_bot.common import metrics
from quant_bot.common.backtest import BacktestResult


class NamedConfig(Protocol):
    name: str
    top_n: int


@dataclass(frozen=True)
class StrategyRun:
    config: NamedConfig
    result: BacktestResult


@dataclass(frozen=True)
class Benchmark:
    label: str
    short: str
    css_class: str
    equity: pd.Series


@dataclass(frozen=True)
class MonthlyPicks:
    period: pd.Period  # 名單的月份（台股 = 使用的營收月份；美股 = 換股月份）
    as_of: pd.Timestamp  # 選股時的股價資料日期
    table: pd.DataFrame  # 本月選股（index = 代號，含 name, weight, status 與各市場的因子欄位）
    dropped: pd.DataFrame  # 上月持有、本月不再入選（index = 代號，含 name）


def summarize_window(equity: pd.Series, start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict[str, float]:
    window = equity.loc[start:end]
    return metrics.summarize(window / window.iloc[0])


def with_status(current: pd.DataFrame, previous_codes: pd.Index) -> pd.DataFrame:
    """標記新進 / 續抱。"""
    return current.assign(status=["續抱" if c in previous_codes else "新進" for c in current.index])
