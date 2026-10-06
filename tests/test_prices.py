import numpy as np
import pandas as pd
import pytest

from quant_bot.tw.prices import PricePanel, clean_adjusted, clean_panel, merge_by_code, yahoo_tickers

DAYS = pd.bdate_range("2024-01-01", periods=6)


def test_spike_that_reverts_is_neutralized():
    adj = pd.DataFrame({"A": [100, 101, 10_000, 102, 103, 104]}, index=DAYS, dtype=float)
    cleaned = clean_adjusted(adj)["A"]
    assert cleaned.max() < 115
    assert cleaned.iloc[-1] == pytest.approx(104, rel=0.02)


def test_normal_moves_are_untouched():
    adj = pd.DataFrame({"A": [100, 109, 100, 105, 95, 100]}, index=DAYS, dtype=float)
    pd.testing.assert_series_equal(clean_adjusted(adj)["A"], adj["A"], check_exact=False)


def test_non_positive_prices_are_ignored():
    adj = pd.DataFrame({"A": [100, 100, -50, 100, 100, 100]}, index=DAYS, dtype=float)
    assert clean_adjusted(adj)["A"].min() == pytest.approx(100)


def test_keeps_nan_before_listing():
    adj = pd.DataFrame({"A": [np.nan, np.nan, 50, 51, 52, 53], "B": [10.0] * 6}, index=DAYS)
    cleaned = clean_adjusted(adj)
    assert cleaned["A"].iloc[:2].isna().all()
    assert cleaned["A"].iloc[2] == 50


def test_drops_days_with_almost_no_quotes():
    adj = pd.DataFrame({c: [10.0] * 6 for c in "ABCD"}, index=DAYS)
    adj.iloc[3, 1:] = np.nan
    assert DAYS[3] not in clean_adjusted(adj).index


def test_clean_panel_aligns_all_fields():
    adj = pd.DataFrame({c: [10.0] * 6 for c in "AB"}, index=DAYS)
    adj.iloc[2, :] = np.nan
    panel = clean_panel(PricePanel(adj, adj.copy(), adj.copy()))
    assert panel.close.index.equals(panel.adj_close.index)
    assert len(panel.volume) == 5


def test_yahoo_tickers_map_markets_to_suffixes():
    mapping = yahoo_tickers({"sii": {"2330"}, "otc": {"6488", "2330"}})
    assert mapping["2330"] == ["2330.TW", "2330.TWO"] or mapping["2330"] == ["2330.TWO", "2330.TW"]
    assert mapping["6488"] == ["6488.TWO"]


def test_merge_by_code_prefers_longer_history_and_fills_gaps():
    frame = pd.DataFrame(
        {"1234.TW": [np.nan, np.nan, 3, 4, 5, 6], "1234.TWO": [1, 2, 3, np.nan, np.nan, np.nan]},
        index=DAYS,
        dtype=float,
    )
    merged = merge_by_code(frame, {"1234": ["1234.TW", "1234.TWO"], "9999": ["9999.TW"]})
    assert list(merged["1234"]) == [1, 2, 3, 4, 5, 6]
    assert "9999" not in merged.columns


def test_return_across_suspension_gap_is_kept():
    adj = pd.DataFrame({"A": [100, np.nan, np.nan, 105, 106, 107], "B": [10.0] * 6}, index=DAYS)
    adj.loc[DAYS[1:3], "B"] = 10.0
    assert clean_adjusted(adj)["A"].iloc[-1] == pytest.approx(107)
