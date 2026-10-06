import numpy as np
import pandas as pd
import pytest

from quant_bot.common.backtest import BacktestResult
from quant_bot.common.svg_chart import Line, line_chart
from quant_bot.common.portfolio import Benchmark, MonthlyPicks, StrategyRun
from quant_bot.tw.pipeline import STRATEGIES
from quant_bot.tw.web_spec import TW_SPEC
from quant_bot.web.report import ReportData, render
from quant_bot.web.spec import pct, tone

DAYS = pd.bdate_range("2014-04-11", "2026-10-06")


def _curve(drift: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumprod(1 + rng.normal(drift, 0.01, len(DAYS))), index=DAYS)


def _run(config, seed) -> StrategyRun:
    equity = _curve(0.0004, seed)
    months = DAYS[::21]
    return StrategyRun(
        config,
        BacktestResult(
            equity=equity,
            turnover=pd.Series(0.4, index=months),
            costs=pd.Series(0.002, index=months),
            holdings={d: pd.Series({"2330": 1.0}) for d in months},
        ),
    )


@pytest.fixture
def report_data() -> ReportData:
    table = pd.DataFrame(
        {
            "name": ["台積電", "<script>"],
            "industry": ["半導體業", "其他"],
            "yoy_3": [0.42, -0.05],
            "yoy_1": [0.35, 0.0],
            "rev_3m": [8.5e8, 2.0e6],
            "close": [1050.0, 22.5],
            "weight": [0.5, 0.5],
            "status": ["新進", "續抱"],
        },
        index=pd.Index(["2330", "9999"], name="code"),
    )
    dropped = pd.DataFrame({"name": ["鴻海"]}, index=pd.Index(["2317"], name="code"))
    data = ReportData(
        spec=TW_SPEC,
        picks=MonthlyPicks(pd.Period("2026-08", "M"), DAYS[-1], table, dropped),
        runs=[_run(c, i) for i, c in enumerate(STRATEGIES)],
        benchmarks=(
            Benchmark("加權報酬指數（大盤，含息）", "大盤", "s-market", _curve(0.0003, 98)),
            Benchmark("0050 買進持有", "0050", "s-bench", _curve(0.0003, 99)),
        ),
        generated_at=pd.Timestamp("2026-10-06 12:00"),
    )
    return data


@pytest.fixture
def report_html(report_data) -> str:
    return render(report_data)


def test_report_fills_every_placeholder(report_html):
    assert "{{" not in report_html


def test_report_lists_picks_and_sells(report_html):
    assert "台積電" in report_html and "2317" in report_html
    assert "2026 年 8 月" in report_html


def test_report_escapes_names(report_html):
    assert "<script>" not in report_html
    assert "&lt;script&gt;" in report_html


def test_report_marks_primary_strategy(report_html):
    assert report_html.count("主策略</span>") == 1


def test_pct_and_tone_follow_taiwan_colors():
    assert pct(0.1234) == "+12.3%"
    assert pct(-0.05) == "-5.0%"
    assert pct(float("nan")) == "—"
    assert tone(0.1) == "up" and tone(-0.1) == "down" and tone(0) == "flat"


def test_line_chart_produces_one_polyline_per_series():
    svg = line_chart([Line("a", _curve(0.001, 1), "s-a"), Line("b", _curve(-0.0005, 2), "s-b")])
    assert svg.count("<polyline") == 2
    assert svg.startswith("<svg")


def test_line_chart_linear_scale_for_drawdowns():
    dd = pd.Series(np.linspace(0, -0.3, len(DAYS)), index=DAYS)
    svg = line_chart([Line("dd", dd, "s")], log_scale=False, y_format=lambda v: f"{v * 100:.0f}%")
    assert "-30%" in svg or "-25%" in svg


def test_report_answers_vs_market(report_html):
    assert "主策略有沒有贏大盤" in report_html
    assert "完整年度勝率" in report_html
    assert "主策略<br>− 大盤" in report_html
    assert report_html.count('class="swatch s-market"') >= 3  # 圖例、摘要表、逐年表
