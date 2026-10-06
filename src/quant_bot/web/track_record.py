"""事後表現：已發布名單的真實紀錄，以及回測期間的逐月對照。

真實紀錄的計算方式：
- 進場：發布時股價資料日（as_of）的下一個交易日收盤
- 出場：下一期名單的進場日收盤；最新一期算到最近交易日（進行中）
- 期間內等權重買進持有，不再平衡；未扣交易成本
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from quant_bot.web.archive import PublishedMonth

COLUMNS = ["period", "entry", "exit", "ongoing", "n", "strategy", "market", "excess"]


def _next_trading_day(days: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    later = days[days > date]
    return later[0] if len(later) else None


def _window_return(prices: pd.Series, entry: pd.Timestamp, exit_: pd.Timestamp) -> float:
    px = prices.loc[:exit_].ffill()
    start, end = px.get(entry), px.iloc[-1] if len(px) else None
    if start is None or pd.isna(start) or end is None or pd.isna(end):
        return float("nan")
    return float(end / start - 1)


def _weights(month: PublishedMonth, variant: str | None) -> pd.Series | None:
    if variant is None:
        return month.weights
    codes = month.variants.get(variant)
    if codes is None:
        return None  # 這一期沒有這個實驗名單
    return pd.Series(1.0 / len(codes), index=list(codes)) if codes else pd.Series(dtype=float)


def published_record(
    months: Sequence[PublishedMonth], prices: pd.DataFrame, market: pd.Series, variant: str | None = None
) -> pd.DataFrame:
    """variant=None 為正式名單；給名稱則改用該期的實驗名單（等權重），沒有的期別報酬為 NaN。"""
    days = prices.index
    entries = [_next_trading_day(days, m.as_of) for m in months]
    rows = []
    for i, (month, entry) in enumerate(zip(months, entries)):
        if entry is None:  # 剛發布，還沒有下一個交易日
            rows.append({"period": month.period, "entry": None, "exit": None, "ongoing": True, "n": len(month.weights)})
            continue
        next_entry = next((e for e in entries[i + 1 :] if e is not None), None)
        exit_ = next_entry or days[-1]
        month_weights = _weights(month, variant)
        if month_weights is None or month_weights.empty:
            strategy = float("nan")
        else:
            stock_returns = pd.Series(
                {code: _window_return(prices[code], entry, exit_) for code in month_weights.index if code in prices},
                dtype=float,
            ).dropna()
            weights = month_weights.reindex(stock_returns.index)
            strategy = float((stock_returns * weights).sum() / weights.sum()) if weights.sum() else float("nan")
        bench = _window_return(market, entry, exit_)
        rows.append(
            {
                "period": month.period,
                "entry": entry,
                "exit": exit_,
                "ongoing": next_entry is None,
                "n": len(month.weights),
                "strategy": strategy,
                "market": bench,
                "excess": strategy - bench,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def backtest_periods(
    equity: pd.Series, holdings: Mapping[pd.Timestamp, pd.Series], market: pd.Series
) -> pd.DataFrame:
    """回測中每一期（兩次換股之間）的策略與大盤報酬。"""
    dates = sorted(holdings)
    rows = []
    for start, end in zip(dates, [*dates[1:], equity.index[-1]]):
        if end <= start:
            continue
        rows.append(
            {
                "entry": start,
                "exit": end,
                "n": len(holdings[start]),
                "strategy": float(equity.loc[end] / equity.loc[start] - 1),
                "market": _window_return(market, start, end),
            }
        )
    df = pd.DataFrame(rows)
    return df.assign(excess=df["strategy"] - df["market"]) if len(df) else df


def cumulative(returns: pd.Series) -> float:
    return float((1 + returns.dropna()).prod() - 1)
