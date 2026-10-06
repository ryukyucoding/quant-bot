import pandas as pd

from quant_bot.tw.notify import format_monthly_message
from tests.test_report import report_data  # noqa: F401  (pytest fixture)


def test_message_lists_buys_sells_and_holds(report_data):
    text = format_monthly_message(report_data)
    assert "新進，要買（1）" in text and "<code>2330</code> 台積電" in text
    assert "剔除，要賣（1）" in text and "2317" in text
    assert "續抱（1）" in text
    assert "完整年度贏" in text
    assert "完整報告見附件" in text


def test_message_escapes_names_and_includes_url(report_data):
    text = format_monthly_message(report_data, report_url="https://claude.ai/artifact/x?a=1&b=2")
    assert "<script>" not in text
    assert "&amp;b=2" in text


def test_message_with_no_changes(report_data):
    picks = report_data.picks
    empty_drop = picks.dropped.iloc[0:0]
    data = type(report_data)(
        picks=type(picks)(picks.period, picks.as_of, picks.table, empty_drop),
        runs=report_data.runs,
        benchmarks=report_data.benchmarks,
        generated_at=pd.Timestamp("2026-10-06"),
    )
    assert "剔除，要賣（0）</b>\n（無）" in format_monthly_message(data)
