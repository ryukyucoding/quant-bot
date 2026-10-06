import pandas as pd
import pytest

from quant_bot.common.backtest import buy_and_hold, run_backtest
from quant_bot.common.costs import ZERO_COST, CostModel, tw_stock_costs

DATES = pd.bdate_range("2024-01-01", periods=5)


@pytest.fixture
def prices() -> pd.DataFrame:
    return pd.DataFrame(
        {"A": [100, 110, 121, 121, 133.1], "B": [50, 50, 25, 25, 50]},
        index=DATES,
        dtype=float,
    )


def test_single_asset_full_weight_tracks_price(prices):
    result = run_backtest(prices, {DATES[0]: pd.Series({"A": 1.0})}, ZERO_COST)
    assert result.equity.iloc[-1] == pytest.approx(1.331)


def test_half_cash_earns_half_return(prices):
    result = run_backtest(prices, {DATES[0]: pd.Series({"A": 0.5})}, ZERO_COST)
    assert result.equity.iloc[1] == pytest.approx(1.05)


def test_weights_drift_between_rebalances(prices):
    # 50/50, A +10%, B 0% -> nav 1.05；之後 B 腰斬，A 的權重已漂移到 0.55/1.05
    result = run_backtest(prices, {DATES[0]: pd.Series({"A": 0.5, "B": 0.5})}, ZERO_COST)
    expected_day2 = 1.05 * (1 + (0.55 / 1.05) * 0.10 + (0.50 / 1.05) * -0.5)
    assert result.equity.iloc[2] == pytest.approx(expected_day2)


def test_rebalance_costs_are_deducted(prices):
    costs = CostModel(buy_rate=0.01, sell_rate=0.02)
    targets = {DATES[0]: pd.Series({"A": 1.0}), DATES[1]: pd.Series({"B": 1.0})}
    result = run_backtest(prices, targets, costs)
    assert result.costs[DATES[0]] == pytest.approx(0.01)
    assert result.costs[DATES[1]] == pytest.approx(0.01 + 0.02)
    assert result.equity.iloc[1] == pytest.approx(0.99 * 1.10 * (1 - 0.03))
    assert result.turnover[DATES[1]] == pytest.approx(1.0)


def test_holdings_are_recorded_per_rebalance(prices):
    targets = {DATES[0]: pd.Series({"A": 0.5, "B": 0.5}), DATES[3]: pd.Series({"A": 1.0, "B": 0.0})}
    result = run_backtest(prices, targets, ZERO_COST)
    assert list(result.holdings[DATES[3]].index) == ["A"]


def test_rejects_weights_above_one(prices):
    with pytest.raises(ValueError):
        run_backtest(prices, {DATES[0]: pd.Series({"A": 0.8, "B": 0.4})}, ZERO_COST)


def test_rejects_negative_weights(prices):
    with pytest.raises(ValueError):
        run_backtest(prices, {DATES[0]: pd.Series({"A": -0.1})}, ZERO_COST)


def test_rejects_unknown_tickers(prices):
    with pytest.raises(ValueError):
        run_backtest(prices, {DATES[0]: pd.Series({"ZZZ": 1.0})}, ZERO_COST)


def test_rejects_empty_targets(prices):
    with pytest.raises(ValueError):
        run_backtest(prices, {}, ZERO_COST)


def test_missing_prices_are_held_flat(prices):
    gappy = prices.assign(A=[100, None, None, 121, 133.1])
    result = run_backtest(gappy, {DATES[0]: pd.Series({"A": 1.0})}, ZERO_COST)
    assert result.equity.iloc[1] == pytest.approx(1.0)
    assert result.equity.iloc[-1] == pytest.approx(1.331)


def test_buy_and_hold_normalizes_to_one(prices):
    curve = buy_and_hold(prices["A"], DATES[1])
    assert curve.iloc[0] == 1.0
    assert curve.iloc[-1] == pytest.approx(1.21)


def test_tw_costs_include_tax_on_sell_only():
    model = tw_stock_costs(fee_discount=1.0, slippage=0.0)
    assert model.buy_rate == pytest.approx(0.001425)
    assert model.sell_rate == pytest.approx(0.004425)


@pytest.mark.parametrize("discount", [0, 1.5])
def test_tw_costs_reject_bad_discount(discount):
    with pytest.raises(ValueError):
        tw_stock_costs(fee_discount=discount)


def test_cost_model_rejects_absurd_rates():
    with pytest.raises(ValueError):
        CostModel(buy_rate=0.5, sell_rate=0.0)
