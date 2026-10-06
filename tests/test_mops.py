from pathlib import Path

import pandas as pd
import pytest

from quant_bot.tw.mops import month_url, parse_month_html

FIXTURE = Path(__file__).parent / "fixtures" / "mops_sii_113_6.html"


@pytest.fixture(scope="module")
def parsed() -> pd.DataFrame:
    html = FIXTURE.read_bytes().decode("big5", errors="replace")
    return parse_month_html(html, 2024, 6, "sii")


def test_month_url_converts_to_roc_year():
    assert month_url(2024, 6, "otc").endswith("/otc/t21sc03_113_6_0.html")


def test_month_url_rejects_unknown_market():
    with pytest.raises(ValueError):
        month_url(2024, 6, "nasdaq")


def test_parses_known_company_values(parsed):
    taiwan_cement = parsed.set_index("code").loc["1101"]
    assert taiwan_cement["name"] == "台泥"
    assert taiwan_cement["industry"] == "水泥工業"
    assert taiwan_cement["revenue"] == 13_659_543
    assert taiwan_cement["rev_last_year"] == 8_816_109


def test_excludes_subtotal_rows_and_keeps_only_four_digit_codes(parsed):
    assert parsed["code"].str.fullmatch(r"\d{4}").all()
    assert parsed["code"].is_unique


def test_covers_most_listed_companies(parsed):
    assert len(parsed) > 800
    assert "2330" in set(parsed["code"])
    assert (parsed["period"] == pd.Period("2024-06", freq="M")).all()


def test_raises_when_page_has_no_tables():
    with pytest.raises(ValueError):
        parse_month_html("<html><table><tr><td>x</td></tr></table></html>", 2024, 6, "sii")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("('產業別：電子零組件業', '產業別：電子零組件業')", "電子零組件業"),
        ("產業別：金融保險業（其中金控公司係控股公司） 單位：千元", "金融保險業"),
        ("產業別：水泥工業 單位：千元", "水泥工業"),
    ],
)
def test_industry_header_is_normalized(header, expected):
    from quant_bot.tw.mops import _INDUSTRY_RE, _normalize_industry

    assert _normalize_industry(_INDUSTRY_RE.search(header).group(1)) == expected
