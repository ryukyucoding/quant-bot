"""台股日價格：上市 .TW / 上櫃 .TWO 代號對應，以及依漲跌幅限制清理錯價。通用部分在 common.prices。"""

from __future__ import annotations

import pandas as pd

from quant_bot.common import prices as common
from quant_bot.common.prices import PricePanel, download_panel, load_panel, merge_by_code, save_panel

__all__ = [
    "PricePanel", "clean_adjusted", "clean_panel", "download_panel", "load_panel", "merge_by_code",
    "save_panel", "yahoo_tickers",
]

SUFFIX = {"sii": ".TW", "otc": ".TWO"}
DAILY_LIMIT = 0.105  # 台股漲跌幅上限 10%（2015/6 前為 7%），留一點容差


def yahoo_tickers(codes_by_market: dict[str, set[str]]) -> dict[str, list[str]]:
    """每個代號對應的 yahoo ticker 清單（曾轉板的股票會同時有 .TW / .TWO）。"""
    mapping: dict[str, list[str]] = {}
    for market, codes in codes_by_market.items():
        for code in sorted(codes):
            mapping.setdefault(code, []).append(code + SUFFIX[market])
    return mapping


def clean_adjusted(adj_close: pd.DataFrame) -> pd.DataFrame:
    """還原權值價已處理除權息，台股日報酬不可能超過漲跌幅限制：先去掉來回跳點，再把日報酬裁切到限制內。"""
    return common.clean_adjusted(adj_close, spike_threshold=DAILY_LIMIT, clip_limit=DAILY_LIMIT)


def clean_panel(panel: PricePanel) -> PricePanel:
    return common.clean_panel(panel, spike_threshold=DAILY_LIMIT, clip_limit=DAILY_LIMIT)
