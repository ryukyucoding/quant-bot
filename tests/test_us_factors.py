import numpy as np
import pandas as pd
import pytest

from quant_bot.common.prices import PricePanel
from quant_bot.us.factor_strategies import (
    FactorConfig, FactorInputs, build_factor_targets, momentum_12_1, trend_is_up, volatility, weights_combo,
    weights_lowvol, weights_quality,
)
from quant_bot.us.quality import gross_profitability, quarterly_gross_profit
from quant_bot.us.universe import parse_history

DAYS = pd.bdate_range("2020-01-01", "2021-12-31")
HISTORY = parse_history('date,tickers\n2019-01-02,"UP,DOWN,FLAT,NOISY"\n')


def _panel() -> PricePanel:
    n = len(DAYS)
    rng = np.random.default_rng(0)
    adj = pd.DataFrame(
        {
            "UP": np.linspace(50, 150, n),
            "DOWN": np.linspace(150, 50, n),
            "FLAT": 100 + rng.normal(0, 0.05, n).cumsum() * 0.01,
            "NOISY": 100 * np.cumprod(1 + rng.normal(0, 0.03, n)),
            "SPY": np.linspace(300, 400, n),
            "BIL": np.full(n, 91.0),
        },
        index=DAYS,
    )
    return PricePanel(adj, adj, pd.DataFrame(1e6, index=DAYS, columns=adj.columns))


def _inputs(quality=None) -> FactorInputs:
    q = quality if quality is not None else pd.DataFrame(columns=["ticker", "end", "filed", "gpa"])
    return FactorInputs(_panel(), HISTORY, q)


# ---------- 訊號 ----------

def test_trend_uses_completed_month_ends_only():
    rising = pd.Series(np.linspace(100, 200, len(DAYS)), index=DAYS)
    assert trend_is_up(rising, pd.Timestamp("2021-06-01"))
    falling = rising.iloc[::-1].set_axis(DAYS)
    assert not trend_is_up(falling, pd.Timestamp("2021-06-01"))
    assert trend_is_up(falling, pd.Timestamp("2020-03-02"))  # 資料不足 10 個月 → 預設持有大盤


def test_momentum_skips_last_month():
    adj = _panel().adj_close
    mom = momentum_12_1(adj, DAYS[-1])
    expected = adj["UP"].iloc[-22] / adj["UP"].iloc[-253] - 1
    assert mom["UP"] == pytest.approx(expected)
    assert mom["UP"] > 0 > mom["DOWN"]
    assert momentum_12_1(adj, DAYS[100]).empty


def test_volatility_needs_enough_history():
    adj = _panel().adj_close
    vol = volatility(adj, DAYS[-1])
    assert vol["NOISY"] > vol["FLAT"]
    assert volatility(adj, DAYS[50]).empty


# ---------- 策略 ----------

def test_lowvol_picks_calmest_members_only():
    weights = weights_lowvol(_inputs(), DAYS[-1], FactorConfig("d", "lowvol", top_n=1))
    assert list(weights.index) in (["FLAT"], ["BIL"]) and "SPY" not in weights.index
    assert list(weights.index) == ["FLAT"]  # BIL、SPY 不是成分股


def test_quality_uses_only_filed_reports():
    quality = pd.DataFrame(
        {"ticker": ["UP", "DOWN"], "end": pd.to_datetime(["2021-06-30"] * 2),
         "filed": pd.to_datetime(["2021-08-01", "2022-01-15"]), "gpa": [0.2, 0.9]}
    )
    weights = weights_quality(_inputs(quality), pd.Timestamp("2021-09-01"), FactorConfig("c", "quality", top_n=2))
    assert list(weights.index) == ["UP"]  # DOWN 的財報還沒申報


def test_combo_splits_half_half_and_goes_to_cash_in_downtrend():
    quality = pd.DataFrame(
        {"ticker": ["UP"], "end": pd.to_datetime(["2021-06-30"]), "filed": pd.to_datetime(["2021-08-01"]), "gpa": [0.3]}
    )
    config = FactorConfig("e", "combo", top_n=1)
    weights = weights_combo(_inputs(quality), DAYS[-1], config)
    assert weights.sum() == pytest.approx(1.0)
    assert weights["UP"] == pytest.approx(1.0)  # 動能與品質都選 UP，權重相加

    falling = _inputs(quality)
    falling.panel.adj_close["SPY"] = np.linspace(400, 300, len(DAYS))
    assert dict(weights_combo(falling, DAYS[-1], config)) == {"BIL": 1.0}


def test_trend_targets_execute_day_after_month_start():
    targets = build_factor_targets(_inputs(), FactorConfig("a", "trend"), pd.Timestamp("2021-11-01"))
    assert list(targets) == [pd.Timestamp("2021-11-02"), pd.Timestamp("2021-12-02")]
    assert all(set(w.index) <= {"SPY", "BIL"} for w in targets.values())


# ---------- 毛利 ÷ 資產 ----------

def _rows(metric, tag, ends, values, filed_lag=40, duration=90):
    ends = pd.to_datetime(ends)
    return pd.DataFrame(
        {"metric": metric, "tag": tag,
         "start": ends - pd.Timedelta(days=duration) if duration else pd.NaT,
         "end": ends, "val": values, "filed": ends + pd.Timedelta(days=filed_lag), "form": "10-Q"}
    )


QUARTER_ENDS = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]


def test_gross_profit_falls_back_to_revenue_minus_cost():
    rows = pd.concat([
        _rows("revenue", "Revenues", QUARTER_ENDS, [100.0] * 5),
        _rows("cost_of_revenue", "CostOfRevenue", QUARTER_ENDS, [60.0] * 5),
        _rows("gross_profit", "GrossProfit", QUARTER_ENDS[:1], [45.0]),
    ])
    gp = quarterly_gross_profit(rows).set_index("end")["gp"]
    assert gp.iloc[0] == 45.0  # 有申報就用申報數字
    assert (gp.iloc[1:] == 40.0).all()


def test_gross_profitability_ttm_over_assets():
    rows = pd.concat([
        _rows("gross_profit", "GrossProfit", QUARTER_ENDS, [10.0, 10.0, 10.0, 10.0, 20.0]),
        _rows("assets", "Assets", QUARTER_ENDS, [200.0] * 5, filed_lag=50, duration=0),
    ])
    table = gross_profitability(rows)
    assert list(table["gpa"]) == pytest.approx([40 / 200, 50 / 200])
    assert table["filed"].iloc[0] == pd.Timestamp("2023-12-31") + pd.Timedelta(days=50)


def test_gross_profitability_empty_without_assets():
    rows = _rows("gross_profit", "GrossProfit", QUARTER_ENDS, [10.0] * 5)
    assert gross_profitability(rows).empty


def test_gross_profit_without_cost_rows():
    rows = pd.concat([
        _rows("revenue", "Revenues", QUARTER_ENDS, [100.0] * 5),
        _rows("assets", "Assets", QUARTER_ENDS, [200.0] * 5, duration=0),
    ])
    assert quarterly_gross_profit(rows).empty
    assert gross_profitability(rows).empty
