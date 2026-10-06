import base64
import hashlib

import pandas as pd

from quant_bot.tw.stock_profiles import SELECTION_COLUMNS, StockProfile
from quant_bot.tw.strategy import Check
from quant_bot.web.site import csp
from quant_bot.web.stocks import SEARCH_SCRIPT, SEARCH_SCRIPT_HASH, render_index, render_stock_page


def _profile(code="5386", picked=True, rank=1, checks=None, selections=None) -> StockProfile:
    revenue = pd.DataFrame({"period": pd.period_range("2025-09", periods=3, freq="M"),
                            "revenue": [1e5, 2e5, 4e5], "yoy_1": [-0.1, 0.5, float("nan")]})
    if selections is None:
        selections = pd.DataFrame([
            {"period": pd.Period("2026-07", "M"), "entry": pd.Timestamp("2026-08-12"), "exit": pd.Timestamp("2026-09-11"),
             "yoy_3": 0.8, "ret": 0.10, "market_ret": 0.02, "live": True, "ongoing": False},
            {"period": pd.Period("2026-08", "M"), "entry": pd.Timestamp("2026-09-11"), "exit": pd.Timestamp("2026-10-06"),
             "yoy_3": 9.5, "ret": -0.05, "market_ret": 0.01, "live": False, "ongoing": True},
        ], columns=SELECTION_COLUMNS)
    return StockProfile(
        code=code, name="青雲<x>", industry="電腦及週邊設備業", as_of=pd.Timestamp("2026-10-06"),
        period=pd.Period("2026-08", "M"), close=291.0,
        latest=pd.Series({"yoy_1": 18.46, "yoy_3": 9.57, "rev_3m": 8.1e6}),
        picked=picked, rank=rank, checks=checks or [Check("營收規模", True, "81 億")],
        revenue=revenue, selections=selections,
        reviews=[{"period": "2026-07", "severity": "high", "summary": "更換會計師事務所"}],
    )


def test_stock_page_sections_and_escaping():
    html = render_stock_page(_profile())
    assert "<title>5386 青雲&lt;x&gt;</title>" in html and "青雲<x>" not in html
    assert "本月入選" in html and "排第 1 名" in html
    assert html.count('<rect class="bar') == 3
    assert 'href="../archive/2026-07.html">實際發布' in html and "持有中" in html
    assert "已結算的 1 次中，有 1 次贏同期大盤" in html
    assert "更換會計師事務所" in html and "<script" not in html


def test_status_sentence_for_failed_and_ranked_out():
    failed = render_stock_page(_profile(picked=False, rank=None, checks=[Check("流動性", False, "x"), Check("股價", True, "y")]))
    assert "未通過「流動性」" in failed
    ranked_out = render_stock_page(_profile(picked=False, rank=49))
    assert "排第 49 名，沒有進前 20 名" in ranked_out


def test_never_selected():
    empty = pd.DataFrame(columns=SELECTION_COLUMNS)
    assert "沒有入選過" in render_stock_page(_profile(picked=False, rank=None, selections=empty))


def test_index_lists_picked_first_with_search_keys():
    html = render_index([_profile("1101", picked=False, rank=None), _profile("5386")])
    assert html.index('data-code="5386"') < html.index('data-code="1101"')
    assert 'data-key="5386 青雲&lt;x&gt; 電腦及週邊設備業"' in html
    assert f"<script>{SEARCH_SCRIPT}</script>" in html


def test_script_hash_matches_and_is_allowed_by_csp():
    expected = "sha256-" + base64.b64encode(hashlib.sha256(SEARCH_SCRIPT.encode()).digest()).decode()
    assert SEARCH_SCRIPT_HASH == expected
    assert f"script-src '{expected}'" in csp((expected,))
    assert "script-src" not in csp()
