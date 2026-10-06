import pandas as pd
import pytest

from quant_bot.tw.factors import availability_date, compute_features, revenue_wide


def _revenue_long(values_by_code: dict[str, list[float]], start="2022-01") -> pd.DataFrame:
    rows = []
    for code, values in values_by_code.items():
        for i, value in enumerate(values):
            period = pd.Period(start, freq="M") + i
            rows.append({"period": str(period), "code": code, "revenue": value, "market": "sii"})
    return pd.DataFrame(rows)


@pytest.fixture
def features() -> pd.DataFrame:
    growing = [100.0] * 12 + [150.0, 160.0, 200.0]
    flat = [100.0] * 15
    return compute_features(revenue_wide(_revenue_long({"1111": growing, "2222": flat})))


def test_yoy_1_compares_same_month_last_year(features):
    row = features.loc[(pd.Period("2023-03", "M"), "1111")]
    assert row["yoy_1"] == pytest.approx(1.0)


def test_yoy_3_uses_three_month_sums(features):
    row = features.loc[(pd.Period("2023-03", "M"), "1111")]
    assert row["yoy_3"] == pytest.approx((150 + 160 + 200) / 300 - 1)
    assert row["rev_3m"] == 510


def test_12m_high_and_streak_flags(features):
    grower = features.loc[(pd.Period("2023-03", "M"), "1111")]
    flat = features.loc[(pd.Period("2023-03", "M"), "2222")]
    assert grower["is_12m_high"] and grower["yoy_streak"]
    assert flat["is_12m_high"] and not flat["yoy_streak"]


def test_early_months_have_no_yoy(features):
    assert pd.isna(features.loc[(pd.Period("2022-06", "M"), "1111")]["yoy_1"])


def test_duplicate_listing_in_same_month_is_collapsed():
    df = pd.concat([_revenue_long({"3333": [10.0]}), _revenue_long({"3333": [12.0]})])
    wide = revenue_wide(df)
    assert wide.loc[pd.Period("2022-01", "M"), "3333"] == 12.0


def test_availability_is_first_trading_day_after_the_tenth():
    days = pd.bdate_range("2024-07-01", "2024-07-31")
    # 2024-07-10 是週三 -> 第一個 > 10 日的交易日是 7/11
    assert availability_date(pd.Period("2024-06", "M"), days) == pd.Timestamp("2024-07-11")


def test_availability_skips_weekend():
    days = pd.bdate_range("2024-08-01", "2024-08-31")
    # 2024-08-10 是週六 → 申報期限順延到 8/12（週一）→ 之後第一個交易日 8/13
    assert availability_date(pd.Period("2024-07", "M"), days) == pd.Timestamp("2024-08-13")


def test_availability_none_when_beyond_data():
    days = pd.bdate_range("2024-07-01", "2024-07-31")
    assert availability_date(pd.Period("2024-07", "M"), days) is None


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        ("2026-10-06", "2026-08"),
        ("2026-10-11", "2026-08"),  # 10/10 是週六 → 期限順延到 10/12（週一）
        ("2026-10-12", "2026-08"),
        ("2026-10-13", "2026-09"),
        ("2026-09-11", "2026-08"),  # 9/10 是週四，正常
    ],
)
def test_latest_published_period_waits_for_deadline(today, expected):
    from quant_bot.tw.factors import latest_published_period

    assert latest_published_period(pd.Timestamp(today)) == pd.Period(expected, "M")


def test_publish_deadline_rolls_over_weekend():
    from quant_bot.tw.factors import publish_deadline

    assert publish_deadline(pd.Period("2026-09", "M")) == pd.Timestamp("2026-10-12")
    assert publish_deadline(pd.Period("2026-08", "M")) == pd.Timestamp("2026-09-10")


def test_availability_after_rolled_deadline():
    days = pd.bdate_range("2026-10-01", "2026-10-31")
    assert availability_date(pd.Period("2026-09", "M"), days) == pd.Timestamp("2026-10-13")
