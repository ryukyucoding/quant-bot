"""近期新聞標題（Google 新聞 RSS）。只取標題、來源、日期與連結，不抓全文。"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests

from quant_bot.common.http import get_with_retry

log = logging.getLogger(__name__)

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
REQUEST_DELAY_SEC = 1.0
MAX_ITEMS = 15


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published: str  # YYYY-MM-DD
    link: str


def parse_rss(xml_text: str, as_of: pd.Timestamp, days: int) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    cutoff = as_of - pd.Timedelta(days=days)
    items = []
    for node in root.iter("item"):
        try:
            published = pd.Timestamp(parsedate_to_datetime(node.findtext("pubDate", ""))).tz_localize(None)
        except (TypeError, ValueError):
            continue
        if not cutoff <= published <= as_of + pd.Timedelta(days=1):
            continue
        items.append(
            NewsItem(
                title=(node.findtext("title") or "").strip(),
                source=(node.findtext("source") or "").strip(),
                published=f"{published:%Y-%m-%d}",
                link=(node.findtext("link") or "").strip(),
            )
        )
    items.sort(key=lambda n: n.published, reverse=True)
    return items[:MAX_ITEMS]


def recent_news(code: str, name: str, as_of: pd.Timestamp, cache_dir: Path, days: int = 30) -> list[NewsItem]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{code}_{as_of:%Y%m%d}.json"
    if path.exists():
        return [NewsItem(**row) for row in json.loads(path.read_text(encoding="utf-8"))]
    query = quote(f"{name} {code} when:{days}d")
    try:
        items = parse_rss(get_with_retry(RSS_URL.format(query=query), max_retries=3).text, as_of, days)
    except (requests.RequestException, ET.ParseError) as exc:
        log.warning("news %s failed: %s", code, exc)
        return []
    time.sleep(REQUEST_DELAY_SEC)
    path.write_text(json.dumps([asdict(n) for n in items], ensure_ascii=False), encoding="utf-8")
    return items
