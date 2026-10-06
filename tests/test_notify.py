import pandas as pd

from quant_bot.web.notify import format_monthly_message
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
        spec=report_data.spec,
        picks=type(picks)(picks.period, picks.as_of, picks.table, empty_drop),
        runs=report_data.runs,
        benchmarks=report_data.benchmarks,
        generated_at=pd.Timestamp("2026-10-06"),
    )
    assert "剔除，要賣（0）</b>\n（無）" in format_monthly_message(data)


def test_message_lists_ai_high_risk(report_data):
    from dataclasses import replace

    from quant_bot.tw.ai_review import AIReview

    reviews = {
        "2330": AIReview("2330", "台積電", "2026-10-06", "例行公告", "none"),
        "9999": AIReview("9999", "<script>", "2026-10-06", "增資", "high",
                         [{"category": "增資或稀釋", "description": "現增", "sources": []}]),
    }
    text = format_monthly_message(replace(report_data, ai_reviews=reviews))
    assert "標記高風險（1）" in text and "增資或稀釋" in text
    assert "<script>" not in text
    clean = format_monthly_message(replace(report_data, ai_reviews={"2330": reviews["2330"]}))
    assert "沒有發現高風險" in clean
