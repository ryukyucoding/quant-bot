import json

import pandas as pd
import pytest

from quant_bot.tw.web_spec import TW_SPEC
from quant_bot.web.archive import load_published, save_snapshot
from quant_bot.web.report import render
from quant_bot.web.site import (
    MarketPages, NavEntry, PageContext, ResearchPage, SiteConfig, build_site, finalize_page, render_archive,
    strip_site_markers, subscribe_html,
)
from quant_bot.web.track_record import published_record
from tests.test_report import report_data  # noqa: F401  (pytest fixture)

CONFIG = SiteConfig(site_name="營收選股", description="測試描述 <x>")
ENTRIES = [NavEntry("tw", "台股名單", ""), NavEntry("us", "美股研究", "us/")]
ROOT_CTX = PageContext("tw", "latest", "", TW_SPEC)
RESEARCH_BODY = '<title>t</title><style></style><div class="wrap"><!--SITE_NAV--><h1>研究</h1><footer><!--SITE_FOOTER--></footer></div>'


@pytest.fixture
def body(report_data):  # noqa: F811
    return render(report_data)


def test_finalize_builds_complete_document(body):
    page = finalize_page(body, CONFIG, ENTRIES, ROOT_CTX, title="營收選股")
    assert page.startswith("<!doctype html>")
    head, rest = page.split("</head>", 1)
    assert "<style>" in head and "Content-Security-Policy" in head
    assert head.count("<title>") == 1
    assert "測試描述 &lt;x&gt;" in head
    assert "<!--SITE_" not in page
    assert 'href="index.html" aria-current=page>台股名單' in rest
    assert 'href="us/index.html">美股研究' in rest
    assert 'href="archive/index.html">台股紀錄' in rest
    assert 'id="subscribe"' in rest


def test_research_page_nav_has_no_archive_or_subscribe_block():
    ctx = PageContext("us", "research", "../")
    page = finalize_page(RESEARCH_BODY, CONFIG, ENTRIES, ctx, title="t")
    assert 'href="../index.html">台股名單' in page
    assert 'href="../us/index.html" aria-current=page>美股研究' in page
    assert "紀錄</a>" not in page and 'id="subscribe"' not in page
    assert 'href="../index.html#subscribe">訂閱推播' in page


def test_csp_blocks_scripts(body):
    page = finalize_page(body, CONFIG, ENTRIES, ROOT_CTX, title="t")
    assert "default-src 'none'" in page
    assert "<script" not in page


def test_subscribe_without_channel_shows_placeholder():
    assert "頻道準備中" in subscribe_html(CONFIG, TW_SPEC)
    with_channel = SiteConfig("n", "d", telegram_channel_url="https://t.me/example")
    assert 'href="https://t.me/example"' in subscribe_html(with_channel, TW_SPEC)


def test_strip_markers_for_single_file(body):
    assert "<!--SITE_" not in strip_site_markers(body)


def test_page_url():
    assert SiteConfig("n", "d", base_url="https://x.github.io/repo/").page_url("us/index.html") == "https://x.github.io/repo/us/index.html"
    assert SiteConfig("n", "d").page_url("index.html") == ""


def test_config_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "site.config.json"
    path.write_text(json.dumps({"site_name": "a", "description": "b", "extra": 1}), encoding="utf-8")
    assert SiteConfig.load(path) == SiteConfig("a", "b")


def test_archive_with_no_history():
    empty = pd.DataFrame(columns=["period", "entry", "exit", "ongoing", "n", "strategy", "market", "excess"])
    html = render_archive(TW_SPEC, empty, pd.DataFrame(columns=["entry", "exit", "n", "strategy", "market", "excess"]))
    assert "還沒有發布紀錄" in html and "{{" not in html
    assert TW_SPEC.first_publish_note in html


def test_build_site_writes_market_and_research(tmp_path, report_data, body):  # noqa: F811
    published_dir = tmp_path / "published"
    save_snapshot(published_dir, report_data.picks, body, pd.Timestamp("2026-10-06 18:30"))
    published = load_published(published_dir)
    prices = pd.DataFrame({"2330": [100.0, 110.0], "9999": [10.0, 10.0]}, index=pd.bdate_range("2026-10-06", periods=2))
    record = published_record(published, prices, pd.Series([1.0, 1.02], index=prices.index))
    backtest = pd.DataFrame(
        {"entry": [pd.Timestamp("2026-01-12")], "exit": [pd.Timestamp("2026-02-11")], "n": [20],
         "strategy": [0.05], "market": [0.02], "excess": [0.03]}
    )
    markets = [MarketPages(TW_SPEC, body, published, published_dir, record, backtest)]
    research = (ResearchPage("us", "美股研究", "us/", RESEARCH_BODY, "美股研究"),)

    site = tmp_path / "site"
    written = build_site(site, CONFIG, markets, research)

    assert {p.relative_to(site).as_posix() for p in written} == {
        "index.html", "archive/2026-08.html", "archive/index.html", "us/index.html",
    }
    archive = (site / "archive" / "index.html").read_text(encoding="utf-8")
    assert 'href="2026-08.html"' in archive and "進行中" in archive and "+2.0%" in archive  # (10%+0%)/2 - 2%
    snapshot = (site / "archive" / "2026-08.html").read_text(encoding="utf-8")
    assert "封存頁面" in snapshot and 'href="../index.html"' in snapshot
    us_index = (site / "us" / "index.html").read_text(encoding="utf-8")
    assert 'href="../index.html">台股名單' in us_index and "<title>美股研究｜營收選股</title>" in us_index
    assert (site / ".nojekyll").exists()


def test_archive_shows_variant_column():
    from quant_bot.web.site import Variant

    record = pd.DataFrame([{"period": pd.Period("2026-09", "M"), "entry": pd.Timestamp("2026-10-12"),
                            "exit": pd.Timestamp("2026-11-12"), "ongoing": False, "n": 20,
                            "strategy": 0.05, "market": 0.02, "excess": 0.03}])
    variant = Variant("ai_filtered", "AI 篩選版", "說明文字", record.assign(strategy=0.07))
    html = render_archive(TW_SPEC, record, record.iloc[0:0].drop(columns=["period", "ongoing"]), variant)
    assert '<th class="num">AI 篩選版</th>' in html
    assert "+7.0%" in html and "說明文字" in html and "{{" not in html
