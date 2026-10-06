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


@dataclass(frozen=True)
class Check:
    label: str
    passed: bool
    detail: str


def explain_checks(
    code: str,
    row: pd.Series | None,
    panel: PricePanel,
    traded_value: pd.DataFrame,
    date: pd.Timestamp,
    config: StrategyConfig,
    industry: str,
) -> list[Check]:
    """逐項列出 code 在 date 是否符合 eligible_codes 的每個條件（與篩選邏輯一一對應）。"""
    has_rev = row is not None
    rev_3m = row["rev_3m"] if has_rev else float("nan")
    rev_ly = row["rev_3m_last_year"] if has_rev else float("nan")
    price = panel.close[code].loc[:date].iloc[-1] if code in panel.close else float("nan")
    value = traded_value[code].loc[:date].iloc[-1] if code in traded_value else float("nan")
    priced_today = code in panel.adj_close and pd.notna(panel.adj_close.at[date, code])
    checks = [
        Check("非金融保險業", industry not in EXCLUDED_INDUSTRIES, industry or "—"),
        Check(
            "營收規模",
            has_rev and rev_3m >= config.min_rev_3m and rev_ly >= config.min_rev_3m / 2,
            f"近三月 {rev_3m / 1e5:,.1f} 億（門檻 {config.min_rev_3m / 1e5:.0f} 億）" if has_rev else "沒有營收資料",
        ),
        Check(f"股價 ≥ {config.min_price:.0f} 元", pd.notna(price) and price >= config.min_price,
              f"{price:,.1f} 元" if pd.notna(price) else "沒有價格"),
        Check("流動性", pd.notna(value) and value >= config.min_traded_value,
              f"近 {LIQUIDITY_WINDOW} 日平均成交 {value / 1e8:,.2f} 億（門檻 {config.min_traded_value / 1e8:.1f} 億）"
              if pd.notna(value) else "沒有成交資料"),
        Check("當日有交易", bool(priced_today), "有" if priced_today else "停牌或無報價"),
    ]
    if config.require_12m_high:
        checks.append(Check("營收創 12 個月新高", has_rev and bool(row["is_12m_high"]), "是" if has_rev and row["is_12m_high"] else "否"))
    if config.require_yoy_streak:
        checks.append(Check("連續三個月營收年增", has_rev and bool(row["yoy_streak"]), "是" if has_rev and row["yoy_streak"] else "否"))
    if config.trend_window:
        px = panel.adj_close[code].loc[:date].tail(config.trend_window) if code in panel.adj_close else pd.Series(dtype=float)
        above = len(px) > 0 and pd.notna(px.iloc[-1]) and px.iloc[-1] > px.mean()
        checks.append(Check(f"股價站上 {config.trend_window} 日均線", bool(above), "是" if above else "否"))
    return checks


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
    schedule = rebalance_schedule(features.index.get_level_values("period").unique(), trading_days, start)
    targets: dict[pd.Timestamp, pd.Series] = {}
    for period, (decision, execution) in schedule.items():
        current = features.xs(period, level="period")
        eligible = eligible_codes(current, panel, traded_value, decision, config, industries)
        targets[execution] = pick(eligible, config)
    return targets


def rebalance_schedule(
    periods, trading_days: pd.DatetimeIndex, start: pd.Timestamp
) -> dict[pd.Period, tuple[pd.Timestamp, pd.Timestamp]]:
    """每個營收月份 → (決策日, 成交日)。"""
    schedule = {}
    for period in sorted(periods):
        decision = availability_date(period, trading_days)
        if decision is None or decision < start:
            continue
        position = trading_days.get_loc(decision) + EXECUTION_LAG_DAYS
        if position < len(trading_days):
            schedule[period] = (decision, trading_days[position])
    return schedule
