"""各市場報告頁的設定：文字、欄位、路徑。報告與網站的程式碼不寫死任何市場的內容。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

import pandas as pd

TAIWAN_COLORS_NOTE = "顏色採台股慣例：紅色為上漲／正報酬，綠色為下跌／負報酬。"


def pct(value: float, digits: int = 1, signed: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.{digits}f}%"


def tone(value: float) -> str:
    if value is None or pd.isna(value) or abs(value) < 1e-9:
        return "flat"
    return "up" if value > 0 else "down"


def num(value: float, digits: int = 2) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:,.{digits}f}"


@dataclass(frozen=True)
class PickColumn:
    header: str  # 表頭 HTML
    cell: Callable[[pd.Series], str]  # 回傳 <td>…</td>


def pct_column(header: str, field: str) -> PickColumn:
    return PickColumn(header, lambda r: f'<td class="num {tone(r[field])}">{pct(r[field])}</td>')


def number_column(header: str, field: str, digits: int = 1, scale: float = 1.0) -> PickColumn:
    return PickColumn(header, lambda r: f'<td class="num">{num(r[field] / scale if pd.notna(r[field]) else r[field], digits)}</td>')


def text_column(header: str, field: str) -> PickColumn:
    return PickColumn(header, lambda r: f'<td class="muted">{escape(str(r.get(field, "")))}</td>')


@dataclass(frozen=True)
class MarketSpec:
    key: str  # 網址與檔名用：tw / us
    label: str  # 台股 / 美股
    name: str  # 台股月營收選股 / 美股季營收選股
    site_dir: str  # 網站中的資料夾（台股在根目錄 = ""）
    eyebrow: str  # 封面小標
    cover_title: Callable[[pd.Period], str]  # 封面大標
    next_update: Callable[[pd.Timestamp], tuple[pd.Timestamp, str]]  # (下次更新日, 說明)
    primary_name: str
    strategy_short: tuple[str, ...]  # 逐年表的欄名，順序同 STRATEGIES
    in_sample_end: pd.Timestamp
    method_html: str  # 本月名單上方的規則說明
    pick_columns: tuple[PickColumn, ...]
    backtest_intro_html: str  # 可用 {BT_START} {IS_END} {OOS_START}
    market_note: str  # 「大盤 = …」
    notes_html: str  # 假設與限制（<li>…</li>）
    sources: str
    period_header: str  # 歷史紀錄表的第一欄名稱
    first_publish_note: str  # 還沒發布時的說明
    subscribe_note: str
    growth_field: str  # 推播訊息中「新進」股票附的成長率欄位
    growth_label: str

    @property
    def oos_start(self) -> pd.Timestamp:
        return self.in_sample_end + pd.Timedelta(days=1)
