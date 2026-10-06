import pandas as pd
import pytest

from quant_bot.common.costs import us_stock_costs
from quant_bot.common.prices import PricePanel
from quant_bot.us.strategy import USStrategyConfig, build_targets, eligible, pick, rebalance_dates
from quant_bot.us.universe import parse_history

DAYS = pd.bdate_range("2024-01-01", "2024-04-30")
HISTORY = parse_history('date,tickers\n2023-01-03,"AAA,BBB,CCC,OUT"\n2024-03-01,"AAA,BBB,CCC,NEW"\n')


def _panel(**prices) -> PricePanel:
    base = {t: 50.0 for t in ("AAA", "BBB", "CCC", "OUT", "NEW", "SPY")}
    base.update(prices)
    adj = pd.DataFrame({t: [v] * len(DAYS) for t, v in base.items()}, index=DAYS)
    return PricePanel(adj, adj, pd.DataFrame(1e6, index=DAYS, columns=adj.columns))


def _quarters(**rows) -> pd.DataFrame:
    defaults = {"end": pd.Timestamp("2023-12-31"), "filed": pd.Timestamp("2024-01-20"), "revenue": 100.0,
                "yoy": 0.1, "yoy_prev": 0.1, "ttm": 400.0, "ttm_high": True}
    return pd.DataFrame([{**defaults, **vals, "ticker": t} for t, vals in rows.items()])


def test_rebalance_on_first_trading_day_of_month():
    assert rebalance_dates(DAYS, pd.Timestamp("2024-02-15"))[:2] == [pd.Timestamp("2024-03-01"), pd.Timestamp("2024-04-01")]


def test_universe_is_point_in_time_membership():
    q = _quarters(AAA={}, OUT={}, NEW={})
    feb = eligible(q, _panel(), HISTORY, pd.Timestamp("2024-02-01"), USStrategyConfig("t"))
    mar = eligible(q, _panel(), HISTORY, pd.Timestamp("2024-03-01"), USStrategyConfig("t"))
    assert set(feb.index) == {"AAA", "OUT"}
    assert set(mar.index) == {"AAA", "NEW"}


def test_filings_after_decision_date_are_ignored():
    q = _quarters(AAA={"filed": pd.Timestamp("2024-02-05")}, BBB={})
    result = eligible(q, _panel(), HISTORY, pd.Timestamp("2024-02-01"), USStrategyConfig("t"))
    assert list(result.index) == ["BBB"]


def test_filters_streak_high_trend_and_price():
    q = _quarters(AAA={"yoy_prev": -0.1}, BBB={"ttm_high": False}, CCC={})
    config = USStrategyConfig("t", require_ttm_high=True, require_yoy_streak=True)
    assert list(eligible(q, _panel(), HISTORY, pd.Timestamp("2024-02-01"), config).index) == ["CCC"]
    assert eligible(q, _panel(CCC=2.0), HISTORY, pd.Timestamp("2024-02-01"), config).empty

    falling = _panel()
    falling.adj_close["CCC"] = range(len(DAYS) + 100, 100, -1)[: len(DAYS)]
    assert eligible(q, falling, HISTORY, pd.Timestamp("2024-04-01"), USStrategyConfig("t", trend_window=20)).loc[
        lambda d: d.index == "CCC"
    ].empty


def test_baseline_holds_all_priced_members():
    result = eligible(_quarters(), _panel(), HISTORY, pd.Timestamp("2024-02-01"), USStrategyConfig("b", rank_by_growth=False))
    weights = pick(result, USStrategyConfig("b", rank_by_growth=False))
    assert set(weights.index) == {"AAA", "BBB", "CCC", "OUT"}
    assert weights.sum() == pytest.approx(1.0)


def test_pick_ranks_by_yoy():
    q = _quarters(AAA={"yoy": 0.5}, BBB={"yoy": 0.9}, CCC={"yoy": 0.1}).set_index("ticker")
    assert list(pick(q, USStrategyConfig("t", top_n=2)).index) == ["BBB", "AAA"]


def test_build_targets_executes_next_day():
    targets = build_targets(_quarters(AAA={}), _panel(), HISTORY, USStrategyConfig("t"), pd.Timestamp("2024-03-01"))
    assert list(targets)[:2] == [pd.Timestamp("2024-03-04"), pd.Timestamp("2024-04-02")]


def test_us_costs():
    model = us_stock_costs(commission=0.001, slippage=0.0)
    assert model.buy_rate == pytest.approx(0.001)
    assert model.sell_rate > model.buy_rate
