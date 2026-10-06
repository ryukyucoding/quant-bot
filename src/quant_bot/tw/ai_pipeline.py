"""對本月入選股逐檔做新聞與重大訊息檢查：預設用關鍵字規則；.env 有 ANTHROPIC_API_KEY 時改用 Claude。有快取就不重跑。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from quant_bot.tw.ai_review import AIReview, load_cached, review_stock, save_cached
from quant_bot.tw.disclosures import recent_announcements
from quant_bot.tw.news import recent_news
from quant_bot.tw.risk_rules import METHOD as RULES_METHOD
from quant_bot.tw.risk_rules import review_by_rules

log = logging.getLogger(__name__)


def make_client(config: Mapping[str, str]):
    """有 ANTHROPIC_API_KEY 才建立 client，否則回傳 None（改用關鍵字規則）。"""
    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    return anthropic.Anthropic(api_key=key)


def run_reviews(client, table: pd.DataFrame, as_of: pd.Timestamp, data_dir: Path) -> dict[str, AIReview]:
    reviews: dict[str, AIReview] = {}
    for code, row in table.iterrows():
        method = RULES_METHOD if client is None else "ai"
        cache = data_dir / f"reviews_{method}" / f"{code}_{as_of:%Y%m%d}.json"  # 規則改版時快取自動失效
        cached = load_cached(cache)
        if cached is not None:
            reviews[code] = cached
            continue
        announcements = recent_announcements(code, as_of, data_dir / "announcements")
        news = recent_news(code, str(row["name"]), as_of, data_dir / "news")
        if client is None:
            review = review_by_rules(code, str(row["name"]), as_of, announcements, news)
        else:
            review = review_stock(client, code, str(row["name"]), str(row.get("industry", "")), as_of, announcements, news)
        save_cached(cache, review)
        reviews[code] = review
        log.info("review (%s) %s %s: %s", method, code, row["name"], review.severity)
    return reviews
