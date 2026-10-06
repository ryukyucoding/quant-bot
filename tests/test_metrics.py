import pandas as pd
import pytest

from quant_bot.common import metrics


def _curve(values, start="2020-01-01", freq="D"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def test_cagr_doubling_over_one_year():
    equity = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01 00:00", "2020-12-31 18:00"]))
    assert metrics.cagr(equity) == pytest.approx(1.0, rel=1e-3)


def test_cagr_zero_length_is_zero():
    equity = pd.Series([1.0, 1.5], index=pd.to_datetime(["2020-01-01", "2020-01-01"]))
    assert metrics.cagr(equity) == 0.0


def test_max_drawdown_finds_peak_to_trough():
    assert metrics.max_drawdown(_curve([1, 2, 1.5, 1.0, 3])) == pytest.approx(-0.5)


def test_sharpe_of_flat_curve_is_zero():
    assert metrics.sharpe(_curve([1, 1, 1, 1])) == 0.0


def test_sharpe_positive_for_rising_noisy_curve():
    assert metrics.sharpe(_curve([1, 1.01, 1.0, 1.03, 1.02, 1.05])) > 0


def test_calendar_year_returns():
    equity = pd.Series(
        [1.0, 1.2, 0.9],
        index=pd.to_datetime(["2020-01-02", "2020-12-31", "2021-12-31"]),
    )
    yearly = metrics.calendar_year_returns(equity)
    assert yearly[2020] == pytest.approx(0.2)
    assert yearly[2021] == pytest.approx(-0.25)


def test_summarize_has_all_keys():
    summary = metrics.summarize(_curve([1, 1.1, 1.05, 1.2]))
    assert set(summary) == {"total_return", "cagr", "max_drawdown", "volatility", "sharpe"}
    assert summary["total_return"] == pytest.approx(0.2)


def test_relative_to_counts_only_complete_years():
    idx = pd.to_datetime(["2020-06-30", "2020-12-31", "2021-12-31", "2022-12-31", "2023-03-31"])
    strat = pd.Series([1.0, 1.1, 1.3, 1.2, 1.25], index=idx)
    bench = pd.Series([1.0, 1.2, 1.25, 1.3, 1.30], index=idx)
    rel = metrics.relative_to(strat, bench)
    # 完整年度只有 2021、2022：2021 策略 +18.2% vs 大盤 +4.2%（贏），2022 -7.7% vs +4.0%（輸）
    assert rel["years_total"] == 2
    assert rel["years_won"] == 1
    assert rel["excess_cagr"] == pytest.approx(metrics.cagr(strat) - metrics.cagr(bench))


def test_relative_to_aligns_dates():
    strat = _curve([1, 1.1, 1.2, 1.3])
    bench = _curve([1, 1.05, 1.1], start="2020-01-02")
    rel = metrics.relative_to(strat, bench)
    assert rel["years_total"] == 0
