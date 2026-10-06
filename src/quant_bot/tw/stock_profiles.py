"""個股查詢頁的資料：每檔股票的本月條件檢查、月營收、入選紀錄、風險檢查紀錄。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from quant_bot.common.portfolio import MonthlyPicks, StrategyRun
from quant_bot.tw.pipeline import PRIMARY, Inputs
from quant_bot.tw.strategy import LIQUIDITY_WINDOW, Check, eligible_codes, explain_checks, rebalance_schedule
from quant_bot.web.archive import PublishedMonth

REVENUE_MONTHS = 36
SELECTION_COLUMNS = ["period", "entry", "exit", "yoy_3", "ret", "market_ret", "live", "ongoing"]


@dataclass(frozen=True)
class StockProfile:
    code: str
    name: str
    industry: str
    as_of: pd.Timestamp
    period: pd.Period  # 本月使用的營收月份
    close: float
    latest: pd.Series | None  # 本月因子（yoy_1, yoy_3, rev_3m, …）
    picked: bool
    rank: int | None  # 在合格股中依近三月營收年增的排名
    checks: list[Check]
    revenue: pd.DataFrame  # period, revenue, yoy_1（近 36 個月）
    selections: pd.DataFrame  # SELECTION_COLUMNS
    reviews: list[dict] = field(default_factory=list)  # 實際發布時的風險檢查


def _selections(run: StrategyRun, inputs: Inputs, market: pd.Series, published: list[PublishedMonth]) -> pd.DataFrame:
    """回測中每次入選的紀錄；實際發布過的期別標 live。"""
    days = inputs.panel.adj_close.index
    periods = inputs.features.index.get_level_values("period").unique()
    by_execution = {ex: period for period, (_, ex) in rebalance_schedule(periods, days, days[0]).items()}
    live_codes = {m.period: set(m.weights.index) for m in published}
    dates = sorted(run.result.holdings)
    adj = inputs.panel.adj_close.ffill()
    rows = []
    for entry, exit_ in zip(dates, [*dates[1:], days[-1]]):
        period = by_execution.get(entry)
        if period is None:
            continue
        market_ret = market.loc[:exit_].iloc[-1] / market.loc[:entry].iloc[-1] - 1
        for code in run.result.holdings[entry].index:
            rows.append({
                "code": code, "period": period, "entry": entry, "exit": exit_,
                "yoy_3": inputs.features.at[(period, code), "yoy_3"],
                "ret": adj.at[exit_, code] / adj.at[entry, code] - 1,
                "market_ret": market_ret,
                "live": code in live_codes.get(period, set()),
                "ongoing": entry == dates[-1],
            })
    return pd.DataFrame(rows, columns=["code", *SELECTION_COLUMNS])


def _reviews_by_code(published: list[PublishedMonth], records: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for month in published:
        for code, review in records.get(month.slug, {}).items():
            out.setdefault(code, []).append({**review, "period": str(month.period)})
    return out


def build_profiles(
    inputs: Inputs,
    primary: StrategyRun,
    picks: MonthlyPicks,
    market: pd.Series,
    published: list[PublishedMonth],
    published_reviews: dict[str, dict],
) -> list[StockProfile]:
    """published_reviews：{期別 slug: {代號: 風險檢查 dict}}（來自 published/*.json 的 ai_reviews）。"""
    as_of, period = picks.as_of, picks.period
    traded_value = inputs.panel.traded_value(LIQUIDITY_WINDOW)
    current = inputs.features.xs(period, level="period")
    selections = _selections(primary, inputs, market, published)
    reviews = _reviews_by_code(published, published_reviews)
    eligible = eligible_codes(current, inputs.panel, traded_value, as_of, PRIMARY, inputs.industries)
    ranks = {code: i for i, code in enumerate(eligible.sort_values("yoy_3", ascending=False).index, start=1)}
    revenue = inputs.features[["revenue", "yoy_1"]].reset_index()
    revenue = revenue[revenue["period"] > period - REVENUE_MONTHS]
    revenue_by_code = dict(tuple(revenue.groupby("code")))
    selections_by_code = dict(tuple(selections.groupby("code")))
    closes = inputs.panel.close.loc[:as_of].ffill().iloc[-1]

    profiles = []
    for code in sorted(inputs.panel.adj_close.columns):
        if not code.isdigit():  # 基準 ETF（0050.TW）不列入
            continue
        row = current.loc[code] if code in current.index else None
        industry = str(inputs.industries.get(code, ""))
        profiles.append(StockProfile(
            code=code,
            name=str(inputs.names.get(code, code)),
            industry=industry,
            as_of=as_of,
            period=period,
            close=float(closes.get(code, float("nan"))),
            latest=row,
            picked=code in picks.table.index,
            rank=ranks.get(code),
            checks=explain_checks(code, row, inputs.panel, traded_value, as_of, PRIMARY, industry),
            revenue=revenue_by_code.get(code, revenue.iloc[0:0]).drop(columns="code").sort_values("period"),
            selections=selections_by_code.get(code, selections.iloc[0:0]).drop(columns="code").sort_values("entry"),
            reviews=reviews.get(code, []),
        ))
    return profiles
