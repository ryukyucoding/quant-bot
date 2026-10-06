import json
from pathlib import Path

import pandas as pd
import pytest

from quant_bot.us.fundamentals import features_as_of, quarter_features, quarterly_revenue
from quant_bot.us.sec import SecClient, extract_revenue_rows, parse_ticker_map
from quant_bot.us.universe import members_on, normalize_ticker, parse_history, tickers_since

FIXTURE = Path(__file__).parent / "fixtures" / "sec_aapl_2016_2020.json"


@pytest.fixture(scope="module")
def aapl_quarters() -> pd.DataFrame:
    rows = extract_revenue_rows(json.loads(FIXTURE.read_text()))
    return quarterly_revenue(rows)


# ---------- universe ----------

HISTORY_CSV = 'date,tickers\n2015-01-02,"AAPL,BRK.B,XOM"\n2018-06-18,"AAPL,BRK.B,NFLX"\n'


def test_parse_history_normalizes_tickers():
    history = parse_history(HISTORY_CSV)
    assert history.iloc[0] == frozenset({"AAPL", "BRK-B", "XOM"})


def test_members_on_uses_latest_change_before_date():
    history = parse_history(HISTORY_CSV)
    assert "XOM" in members_on(history, pd.Timestamp("2018-06-17"))
    assert "NFLX" in members_on(history, pd.Timestamp("2018-06-18"))
    assert members_on(history, pd.Timestamp("2010-01-01")) == frozenset()


def test_tickers_since_includes_removed_members():
    history = parse_history(HISTORY_CSV)
    assert tickers_since(history, pd.Timestamp("2016-01-01")) == {"AAPL", "BRK-B", "XOM", "NFLX"}


def test_normalize_ticker():
    assert normalize_ticker(" brk.b ") == "BRK-B"


# ---------- SEC ----------

def test_parse_ticker_map():
    payload = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}, "1": {"cik_str": 1067983, "ticker": "BRK.B"}}
    assert parse_ticker_map(payload) == {"AAPL": 320193, "BRK-B": 1067983}


def test_sec_client_requires_contact_email():
    with pytest.raises(ValueError):
        SecClient("")


def test_extract_keeps_only_10q_10k_duration_rows():
    rows = extract_revenue_rows(json.loads(FIXTURE.read_text()))
    assert set(rows["form"].str[:4]) <= {"10-Q", "10-K"}
    assert rows["start"].notna().all()


# ---------- 季營收 ----------

def test_apple_q4_is_derived_from_annual_minus_nine_months(aapl_quarters):
    q4_fy19 = aapl_quarters.set_index("end").loc[pd.Timestamp("2019-09-28")]
    assert q4_fy19["revenue"] == pytest.approx(64_040e6)
    assert q4_fy19["filed"] == pd.Timestamp("2019-10-31")


def test_apple_reported_quarter_uses_first_filing(aapl_quarters):
    q1_fy19 = aapl_quarters.set_index("end").loc[pd.Timestamp("2018-12-29")]
    assert q1_fy19["revenue"] == pytest.approx(84_310e6)
    assert q1_fy19["filed"] == pd.Timestamp("2019-01-30")


def test_quarters_are_unique_and_sorted(aapl_quarters):
    assert aapl_quarters["end"].is_unique and aapl_quarters["end"].is_monotonic_increasing


def test_apple_features(aapl_quarters):
    feats = quarter_features(aapl_quarters).set_index("end")
    q4 = feats.loc[pd.Timestamp("2019-09-28")]
    assert q4["yoy"] == pytest.approx(64_040 / 62_900 - 1)
    assert q4["ttm"] == pytest.approx(260_174e6)


def _synthetic(ticker: str, revenues: list[float], start="2020-03-31") -> pd.DataFrame:
    ends = pd.date_range(start, periods=len(revenues), freq="QE")
    return pd.DataFrame({"end": ends, "filed": ends + pd.Timedelta(days=40), "revenue": revenues}).assign(ticker=ticker)


def test_ttm_high_and_streak():
    growing = quarter_features(_synthetic("G", [100.0 + 5 * i for i in range(12)]))
    assert growing["ttm_high"].iloc[-1]
    assert growing["yoy"].iloc[-1] > 0 and growing["yoy_prev"].iloc[-1] > 0
    shrinking = quarter_features(_synthetic("S", [200.0 - 5 * i for i in range(12)]))
    assert not shrinking["ttm_high"].iloc[-1]


def test_ttm_requires_consecutive_quarters():
    q = _synthetic("X", [100.0] * 6)
    gappy = q.drop(index=2).reset_index(drop=True)
    assert quarter_features(gappy)["ttm"].iloc[2:5].isna().all()


def test_features_as_of_respects_filing_date_and_staleness():
    table = pd.concat([quarter_features(_synthetic("A", [100.0] * 10)), quarter_features(_synthetic("B", [50.0] * 3))])
    last_a = table[table["ticker"] == "A"].iloc[-1]
    asof = features_as_of(table, last_a["filed"])  # 申報當天還不能用
    assert asof.loc["A", "end"] < last_a["end"]
    later = features_as_of(table, last_a["filed"] + pd.Timedelta(days=1))
    assert later.loc["A", "end"] == last_a["end"]
    assert "B" not in later.index  # B 最後一季太舊


def test_empty_rows():
    empty = quarterly_revenue(extract_revenue_rows({}))
    assert empty.empty
    assert quarter_features(empty).empty


def test_quarterly_revenue_without_annual_rows_keeps_datetime_types():
    rows = pd.DataFrame(
        {"tag": ["Revenues"] * 2, "start": pd.to_datetime(["2023-01-01", "2023-04-01"]),
         "end": pd.to_datetime(["2023-03-31", "2023-06-30"]), "val": [10.0, 12.0],
         "filed": pd.to_datetime(["2023-05-01", "2023-08-01"]), "form": ["10-Q"] * 2}
    )
    quarters = quarterly_revenue(rows)
    assert pd.api.types.is_datetime64_any_dtype(quarters["end"])
    assert len(quarter_features(quarters)) == 2
