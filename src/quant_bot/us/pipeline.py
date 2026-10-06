"""美股季營收：載入資料、跑所有策略回測（研究用，結果見 scripts/us_factor_research.py）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_bot.common.backtest import buy_and_hold, run_backtest
from quant_bot.common.costs import us_stock_costs
from quant_bot.common.portfolio import Benchmark, StrategyRun
from quant_bot.common.prices import PricePanel, clean_panel, load_panel
from quant_bot.us.strategy import USStrategyConfig, build_targets
from quant_bot.us.universe import load_history

BACKTEST_START = pd.Timestamp("2012-01-01")  # XBRL 普及後再多留兩年算 TTM 新高
IN_SAMPLE_END = pd.Timestamp("2022-12-31")
SPIKE_THRESHOLD = 0.5  # 美股沒有漲跌幅限制，只移除單日 ±50% 又反轉的明顯錯價
MARKET, EQUAL_WEIGHT_ETF = "SPY", "RSP"

PRIMARY = USStrategyConfig(
    "營收創高＋連兩季年增＋站上 200 日線",
    require_ttm_high=True,
    require_yoy_streak=True,
    trend_window=200,
)
STRATEGIES = (
    USStrategyConfig("成分股全部等權重", rank_by_growth=False),
    USStrategyConfig("最新季營收年增 前 20 名"),
    USStrategyConfig("TTM 營收創 8 季新高 前 20 名", require_ttm_high=True),
    PRIMARY,
)


@dataclass(frozen=True)
class USInputs:
    quarters: pd.DataFrame
    panel: PricePanel
    history: pd.Series


def load_inputs(root: Path) -> USInputs:
    data = root / "data" / "us"
    return USInputs(
        quarters=pd.read_parquet(data / "revenue_quarters.parquet"),
        panel=clean_panel(load_panel(root / "data" / "prices" / "us"), spike_threshold=SPIKE_THRESHOLD),
        history=load_history(data / "sp500_history.csv"),
    )


def run_all(inputs: USInputs) -> list[StrategyRun]:
    costs = us_stock_costs()
    runs = []
    for config in STRATEGIES:
        targets = build_targets(inputs.quarters, inputs.panel, inputs.history, config, BACKTEST_START)
        runs.append(StrategyRun(config, run_backtest(inputs.panel.adj_close, targets, costs)))
    return runs


def load_benchmarks(inputs: USInputs, start: pd.Timestamp) -> tuple[Benchmark, ...]:
    """第一個是大盤（SPY，含股利再投入），之後是 S&P 500 等權重 ETF。"""
    curve = lambda t: buy_and_hold(inputs.panel.adj_close[t], start)  # noqa: E731
    return (
        Benchmark("S&P 500（SPY，含息）", "大盤", "s-market", curve(MARKET)),
        Benchmark("S&P 500 等權重（RSP）", "RSP", "s-bench", curve(EQUAL_WEIGHT_ETF)),
    )
