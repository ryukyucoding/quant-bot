import pandas as pd
import pytest

from quant_bot.tw.prices import PricePanel
from quant_bot.tw.strategy import StrategyConfig, build_targets, eligible_codes, pick

DAYS = pd.bdate_range("2024-05-01", "2024-07-31")
PERIOD = pd.Period("2024-06", "M")
CODES = ["1001", "1002", "1003", "2801"]


def _panel(**overrides) -> PricePanel:
    base = {code: 50.0 for code in CODES}
    base.update(overrides)
    adj = pd.DataFrame({c: [v] * len(DAYS) for c, v in base.items()}, index=DAYS)
    vol = pd.DataFrame(2_000_000.0, index=DAYS, columns=adj.columns)
    return PricePanel(adj_close=adj, close=adj, volume=vol)


def _features(**rows) -> pd.DataFrame:
    defaults = {"yoy_3": 0.1, "rev_3m": 1e6, "rev_3m_last_year": 1e6, "is_12m_high": True, "yoy_streak": True}
    records = {code: {**defaults, **vals} for code, vals in rows.items()}
    df = pd.DataFrame.from_dict(records, orient="index")
    df.index.name = "code"
    return df


INDUSTRIES = pd.Series({"1001": "半導體業", "1002": "電子零組件業", "1003": "食品工業", "2801": "金融保險業"})


def _eligible(features, panel, config):
    tv = panel.traded_value(60)
    return eligible_codes(features, panel, tv, DAYS[-1], config, INDUSTRIES)


def test_excludes_financials():
    feats = _features(**{c: {} for c in CODES})
    result = _eligible(feats, _panel(), StrategyConfig("t"))
    assert "2801" not in result.index
    assert set(result.index) == {"1001", "1002", "1003"}


def test_filters_small_revenue_and_tiny_base():
    feats = _features(**{"1001": {"rev_3m": 1000}, "1002": {"rev_3m_last_year": 10}, "1003": {}})
    assert list(_eligible(feats, _panel(), StrategyConfig("t")).index) == ["1003"]


def test_filters_low_price_and_illiquid():
    feats = _features(**{"1001": {}, "1002": {}, "1003": {}})
    panel = _panel(**{"1001": 5.0})
    thin = PricePanel(panel.adj_close, panel.close, panel.volume.assign(**{"1002": 100.0}))
    assert list(_eligible(feats, thin, StrategyConfig("t")).index) == ["1003"]


def test_optional_flags_are_applied():
    feats = _features(**{"1001": {"is_12m_high": False}, "1002": {"yoy_streak": False}, "1003": {}})
    config = StrategyConfig("t", require_12m_high=True, require_yoy_streak=True)
    assert list(_eligible(feats, _panel(), config).index) == ["1003"]


def test_trend_filter_requires_price_above_moving_average():
    feats = _features(**{"1001": {}, "1002": {}})
    panel = _panel()
    falling = panel.adj_close.assign(**{"1001": list(range(len(DAYS) + 100, 100, -1))[: len(DAYS)]})
    rising = falling.assign(**{"1002": list(range(100, 100 + len(DAYS)))})
    trending = PricePanel(rising, rising, panel.volume)
    result = _eligible(feats, trending, StrategyConfig("t", trend_window=20))
    assert list(result.index) == ["1002"]


def test_pick_ranks_by_growth_and_equal_weights():
    feats = _features(**{"1001": {"yoy_3": 0.5}, "1002": {"yoy_3": 0.9}, "1003": {"yoy_3": 0.1}})
    weights = pick(feats, StrategyConfig("t", top_n=2))
    assert list(weights.index) == ["1002", "1001"]
    assert weights.sum() == pytest.approx(1.0)


def test_pick_without_ranking_holds_everything():
    feats = _features(**{c: {} for c in CODES[:3]})
    assert len(pick(feats, StrategyConfig("t", top_n=1, rank_by_growth=False))) == 3


def test_pick_empty_returns_empty():
    assert pick(_features(), StrategyConfig("t")).empty


def test_build_targets_uses_publication_date():
    feats = _features(**{c: {} for c in CODES})
    feats = pd.concat({PERIOD: feats}, names=["period"])
    targets = build_targets(feats, _panel(), INDUSTRIES, StrategyConfig("t"), DAYS[0])
    # 7/11 收盤後決定，7/12 成交
    assert list(targets) == [pd.Timestamp("2024-07-12")]
    assert targets[pd.Timestamp("2024-07-12")].sum() == pytest.approx(1.0)


def test_explain_checks_agrees_with_eligible_codes():
    from quant_bot.tw.strategy import explain_checks

    feats = _features(**{"1001": {}, "1002": {"rev_3m": 1000}, "1003": {"is_12m_high": False}, "2801": {}})
    panel = _panel(**{"1001": 50.0})
    tv = panel.traded_value(60)
    config = StrategyConfig("t", require_12m_high=True, require_yoy_streak=True, trend_window=20)
    eligible = set(eligible_codes(feats, panel, tv, DAYS[-1], config, INDUSTRIES).index)
    for code in feats.index:
        checks = explain_checks(code, feats.loc[code], panel, tv, DAYS[-1], config, INDUSTRIES[code])
        assert all(c.passed for c in checks) == (code in eligible), code
    missing = explain_checks("9999", None, panel, tv, DAYS[-1], config, "")
    assert not missing[1].passed and "沒有營收" in missing[1].detail


def test_rebalance_schedule_maps_period_to_dates():
    from quant_bot.tw.strategy import rebalance_schedule

    schedule = rebalance_schedule([PERIOD], DAYS, DAYS[0])
    assert schedule[PERIOD] == (pd.Timestamp("2024-07-11"), pd.Timestamp("2024-07-12"))
