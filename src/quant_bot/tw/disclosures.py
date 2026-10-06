"""公開資訊觀測站「重大訊息」：列出某公司一段期間的公告，並抓公告全文。

列表：POST ajax_t05st01（依民國年查詢）
全文：POST ajax_t05st01 step=2（序號、發言日期、發言時間）
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import requests
from lxml import html as lxml_html

from quant_bot.common.http import REQUEST_TIMEOUT_SEC, USER_AGENT
from quant_bot.tw.mops import ROC_OFFSET

log = logging.getLogger(__name__)

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"
REQUEST_DELAY_SEC = 1.5
DETAIL_MAX_CHARS = 800  # 送進 AI 的每則全文上限
_ONCLICK_RE = re.compile(r"(seq_no|spoke_time|spoke_date|TYPEK)\.value='([^']*)'")


@dataclass(frozen=True)
class Announcement:
    code: str
    date: str  # YYYY-MM-DD
    time: str
    subject: str
    seq_no: str
    spoke_date: str  # YYYYMMDD
    spoke_time: str  # HHMMSS
    typek: str
    detail: str = ""


def _post(data: dict) -> str:
    resp = requests.post(URL, data=data, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SEC)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY_SEC)
    return resp.content.decode("utf-8", errors="replace")


def parse_list(page: str, code: str) -> list[Announcement]:
    """解析公告列表頁；每列的按鈕 onclick 帶有查全文需要的參數。"""
    tree = lxml_html.fromstring(page)
    items = []
    for row in tree.xpath("//tr[.//input[contains(@onclick, 'seq_no')]]"):
        cells = [re.sub(r"\s+", " ", c.text_content()).strip() for c in row.xpath("./td")]
        params = dict(_ONCLICK_RE.findall(row.xpath(".//input/@onclick")[0]))
        if len(cells) < 5 or not params.get("spoke_date"):
            continue
        roc_date = cells[2]
        y, m, d = (int(x) for x in roc_date.split("/"))
        items.append(
            Announcement(
                code=code, date=f"{y + ROC_OFFSET:04d}-{m:02d}-{d:02d}", time=cells[3], subject=cells[4],
                seq_no=params.get("seq_no", ""), spoke_date=params["spoke_date"],
                spoke_time=params.get("spoke_time", ""), typek=params.get("TYPEK", ""),
            )
        )
    return items


def parse_detail(page: str) -> str:
    text = lxml_html.fromstring(page).text_content()
    text = re.sub(r"\s+", " ", text).strip()
    start = text.find("主旨")
    return text[start:] if start >= 0 else text


def list_announcements(code: str, since: pd.Timestamp, until: pd.Timestamp) -> list[Announcement]:
    items: list[Announcement] = []
    for year in range(since.year, until.year + 1):
        page = _post({
            "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "queryName": "co_id",
            "inpuType": "co_id", "TYPEK": "all", "co_id": code, "year": str(year - ROC_OFFSET),
        })
        items.extend(parse_list(page, code))
    return [a for a in items if since.strftime("%Y-%m-%d") <= a.date <= until.strftime("%Y-%m-%d")]


def fetch_detail(item: Announcement) -> str:
    page = _post({
        "step": "2", "colorchg": "1", "co_id": item.code, "off": "1", "firstin": "1", "TYPEK": item.typek,
        "seq_no": item.seq_no, "spoke_time": item.spoke_time, "spoke_date": item.spoke_date,
    })
    return parse_detail(page)[:DETAIL_MAX_CHARS]


def recent_announcements(
    code: str, as_of: pd.Timestamp, cache_dir: Path, days: int = 60, max_details: int = 12
) -> list[Announcement]:
    """近 days 天的重大訊息（最新的 max_details 則附全文），依 (代號, 日期) 快取。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{code}_{as_of:%Y%m%d}.json"
    if path.exists():
        return [Announcement(**row) for row in json.loads(path.read_text(encoding="utf-8"))]
    try:
        items = sorted(list_announcements(code, as_of - pd.Timedelta(days=days), as_of), key=lambda a: a.date, reverse=True)
        detailed = [Announcement(**{**asdict(a), "detail": fetch_detail(a)}) for a in items[:max_details]]
        items = detailed + items[max_details:]
    except (requests.RequestException, ValueError) as exc:
        log.warning("announcements %s failed: %s", code, exc)
        return []  # 不快取失敗結果，下次重試
    path.write_text(json.dumps([asdict(a) for a in items], ensure_ascii=False), encoding="utf-8")
    return items
