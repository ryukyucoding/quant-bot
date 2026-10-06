"""台股月營收：載入資料、跑所有策略回測、產生本月選股。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_bot.common.backtest import buy_and_hold, run_backtest
from quant_bot.common.costs import tw_stock_costs
from quant_bot.common.portfolio import Benchmark, MonthlyPicks, StrategyRun, summarize_window, with_status
from quant_bot.tw.factors import availability_date, compute_features, latest_published_period, revenue_wide
from quant_bot.tw.prices import PricePanel, clean_panel, load_panel
from quant_bot.tw.strategy import LIQUIDITY_WINDOW, StrategyConfig, build_targets, eligible_codes, pick

BENCHMARK = "0050.TW"
BACKTEST_START = pd.Timestamp("2014-04-01")  # 需 15 個月營收才算得出近三月年增
IN_SAMPLE_END = pd.Timestamp("2022-12-31")  # 之後為樣本外（驗證期）

# 主策略在看回測結果前就決定，其餘為對照組
PRIMARY = StrategyConfig(
    "營收創高＋連三月年增＋站上半年線",
    require_12m_high=True,
    require_yoy_streak=True,
    trend_window=120,
)
STRATEGIES = (
    StrategyConfig("合格股票全部等權重", rank_by_growth=False),
    StrategyConfig("近三月營收年增 前 20 名"),
    StrategyConfig("營收創 12 個月新高 前 20 名", require_12m_high=True),
    PRIMARY,
)


@dataclass(frozen=True)
class Inputs:
    features: pd.DataFrame
    panel: PricePanel
    industries: pd.Series
    names: pd.Series


def load_inputs(root: Path) -> Inputs:
    revenue = pd.read_parquet(root / "data" / "tw_revenue.parquet")
    latest = revenue.sort_values("period").groupby("code").last()
    features = compute_features(revenue_wide(revenue))
    return Inputs(
        features=features,
        panel=clean_panel(load_panel(root / "data" / "prices" / "tw")),
        industries=latest["industry"],
        names=latest["name"],
    )


def run_all(inputs: Inputs) -> list[StrategyRun]:
    costs = tw_stock_costs()
    runs = []
    for config in STRATEGIES:
        targets = build_targets(inputs.features, inputs.panel, inputs.industries, config, BACKTEST_START)
        runs.append(StrategyRun(config, run_backtest(inputs.panel.adj_close, targets, costs)))
    return runs


def load_benchmarks(root: Path, inputs: Inputs, start: pd.Timestamp) -> tuple[Benchmark, ...]:
    """第一個是大盤（含息報酬指數），之後是其他參考基準。"""
    market_path = root / "data" / "taiex_tr.parquet"
    if not market_path.exists():
        raise FileNotFoundError(f"{market_path} missing; run scripts/fetch_tw_index.py")
    market = pd.read_parquet(market_path)["taiex_tr"]
    return (
        Benchmark("加權報酬指數（大盤，含息）", "大盤", "s-market", buy_and_hold(market, start)),
        Benchmark("0050 買進持有", "0050", "s-bench", buy_and_hold(inputs.panel.adj_close[BENCHMARK], start)),
    )


def _selection(inputs: Inputs, period: pd.Period, date: pd.Timestamp, config: StrategyConfig) -> pd.DataFrame:
    current = inputs.features.xs(period, level="period")
    traded_value = inputs.panel.traded_value(LIQUIDITY_WINDOW)
    eligible = eligible_codes(current, inputs.panel, traded_value, date, config, inputs.industries)
    chosen = pick(eligible, config)
    return eligible.loc[chosen.index].assign(weight=chosen)


def monthly_picks(inputs: Inputs, today: pd.Timestamp, config: StrategyConfig = PRIMARY) -> MonthlyPicks:
    period = min(latest_published_period(today), inputs.features.index.get_level_values("period").max())
    as_of = inputs.panel.adj_close.index[-1]
    current = _selection(inputs, period, as_of, config)

    prev_period = period - 1
    prev_date = availability_date(prev_period, inputs.panel.adj_close.index) or as_of
    previous = _selection(inputs, prev_period, prev_date, config)

    def describe(df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            name=inputs.names.reindex(df.index),
            industry=inputs.industries.reindex(df.index),
            close=inputs.panel.close.loc[:as_of].iloc[-1].reindex(df.index),
        )

    table = with_status(describe(current), previous.index)
    dropped = describe(previous.loc[previous.index.difference(current.index)])
    return MonthlyPicks(period=period, as_of=as_of, table=table, dropped=dropped)
