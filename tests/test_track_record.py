import json

import numpy as np
import pandas as pd
import pytest

from quant_bot.web.archive import PublishedMonth, from_record, load_published, save_snapshot, to_record
from quant_bot.common.portfolio import MonthlyPicks
from quant_bot.web.track_record import backtest_periods, cumulative, published_record

DAYS = pd.bdate_range("2026-07-01", "2026-09-30")


def _month(period: str, as_of: str, codes: list[str]) -> PublishedMonth:
    weights = pd.Series(1 / len(codes), index=codes)
    return PublishedMonth(
        period=pd.Period(period, "M"),
        as_of=pd.Timestamp(as_of),
        published_at=pd.Timestamp(as_of) + pd.Timedelta(hours=18),
        weights=weights,
        names=pd.Series(codes, index=codes),
        dropped=(),
    )


@pytest.fixture
def prices() -> pd.DataFrame:
    n = len(DAYS)
    return pd.DataFrame(
        {"A": np.linspace(100, 200, n), "B": np.full(n, 50.0), "C": np.linspace(10, 5, n)},
        index=DAYS,
    )


def test_published_window_runs_from_next_day_to_next_entry(prices):
    months = [_month("2026-06", "2026-07-13", ["A", "B"]), _month("2026-07", "2026-08-11", ["C"])]
    market = prices["B"] * 1.0
    record = published_record(months, prices, market)

    first = record.iloc[0]
    assert first["entry"] == pd.Timestamp("2026-07-14")
    assert first["exit"] == pd.Timestamp("2026-08-12")
    assert not first["ongoing"]
    a_ret = prices.loc["2026-08-12", "A"] / prices.loc["2026-07-14", "A"] - 1
    assert first["strategy"] == pytest.approx(a_ret / 2)
    assert first["market"] == pytest.approx(0.0)

    last = record.iloc[1]
    assert last["ongoing"] and last["exit"] == DAYS[-1]
    assert last["strategy"] < 0


def test_month_published_after_last_price_is_pending(prices):
    record = published_record([_month("2026-09", "2026-09-30", ["A"])], prices, prices["B"])
    assert record.iloc[0]["ongoing"] and pd.isna(record.iloc[0]["strategy"])


def test_missing_stock_is_excluded_and_weights_renormalized(prices):
    record = published_record([_month("2026-06", "2026-07-13", ["A", "ZZZ"])], prices, prices["B"])
    a_ret = prices["A"].iloc[-1] / prices.loc["2026-07-14", "A"] - 1
    assert record.iloc[0]["strategy"] == pytest.approx(a_ret)


def test_backtest_periods_and_cumulative(prices):
    equity = prices["A"] / 100
    holdings = {DAYS[0]: pd.Series({"A": 1.0}), DAYS[20]: pd.Series({"A": 0.5, "B": 0.5})}
    periods = backtest_periods(equity, holdings, prices["B"])
    assert list(periods["n"]) == [1, 2]
    assert periods["excess"].equals(periods["strategy"] - periods["market"])
    assert cumulative(periods["strategy"]) == pytest.approx(equity.iloc[-1] / equity.iloc[0] - 1)


def test_snapshot_is_frozen_once_published(tmp_path):
    table = pd.DataFrame({"name": ["台積電"], "weight": [1.0]}, index=pd.Index(["2330"], name="code"))
    picks = MonthlyPicks(pd.Period("2026-08", "M"), pd.Timestamp("2026-09-11"), table, table.iloc[0:0])
    assert save_snapshot(tmp_path, picks, "<p>v1</p>", pd.Timestamp("2026-09-11 18:30"))
    assert not save_snapshot(tmp_path, picks, "<p>v2</p>", pd.Timestamp("2026-09-12"))
    assert (tmp_path / "2026-08.html").read_text(encoding="utf-8") == "<p>v1</p>"
    assert save_snapshot(tmp_path, picks, "<p>v3</p>", pd.Timestamp("2026-09-12"), force=True)

    (month,) = load_published(tmp_path)
    assert month.slug == "2026-08"
    assert month.weights["2330"] == 1.0 and month.names["2330"] == "台積電"


def test_record_roundtrip():
    table = pd.DataFrame(
        {"name": ["A公司", "B公司"], "weight": [0.5, 0.5]}, index=pd.Index(["1111", "2222"], name="code")
    )
    dropped = pd.DataFrame({"name": ["C"]}, index=pd.Index(["3333"], name="code"))
    picks = MonthlyPicks(pd.Period("2026-08", "M"), pd.Timestamp("2026-09-11"), table, dropped)
    record = json.loads(json.dumps(to_record(picks, pd.Timestamp("2026-09-11 18:30"))))
    month = from_record(record)
    assert list(month.weights.index) == ["1111", "2222"]
    assert month.dropped == ("3333",)


def test_load_published_missing_dir(tmp_path):
    assert load_published(tmp_path / "none") == []


def test_variant_record_uses_variant_codes(prices):
    base = _month("2026-06", "2026-07-13", ["A", "C"])
    month = PublishedMonth(base.period, base.as_of, base.published_at, base.weights, base.names, (), {"ai_filtered": ("A",)})
    plain = published_record([month], prices, prices["B"])
    variant = published_record([month], prices, prices["B"], variant="ai_filtered")
    a_ret = prices["A"].iloc[-1] / prices.loc["2026-07-14", "A"] - 1
    assert variant.iloc[0]["strategy"] == pytest.approx(a_ret)
    assert plain.iloc[0]["strategy"] < variant.iloc[0]["strategy"]  # C 一路下跌，被排除後較好
    missing = published_record([base], prices, prices["B"], variant="ai_filtered")
    assert pd.isna(missing.iloc[0]["strategy"])


def test_snapshot_keeps_variants_and_extra(tmp_path):
    table = pd.DataFrame({"name": ["台積電"], "weight": [1.0]}, index=pd.Index(["2330"], name="code"))
    picks = MonthlyPicks(pd.Period("2026-08", "M"), pd.Timestamp("2026-09-11"), table, table.iloc[0:0])
    save_snapshot(tmp_path, picks, "<p/>", pd.Timestamp("2026-09-11"), variants={"ai_filtered": []}, extra={"ai_reviews": {"2330": "x"}})
    (month,) = load_published(tmp_path)
    assert month.variants == {"ai_filtered": ()}
    assert json.loads((tmp_path / "2026-08.json").read_text(encoding="utf-8"))["ai_reviews"] == {"2330": "x"}
