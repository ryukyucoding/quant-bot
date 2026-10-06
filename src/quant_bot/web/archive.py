"""已發布月報的封存：每月名單一旦公開就凍結，之後只讀不改，用來計算真實紀錄。

published/
  2026-08.json   名單、發布時間（計算事後表現用）
  2026-08.html   當時的報告頁面（保留網站導覽的標記，建站時再套上）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quant_bot.common.portfolio import MonthlyPicks


@dataclass(frozen=True)
class PublishedMonth:
    period: pd.Period  # 使用的營收月份
    as_of: pd.Timestamp  # 選股時的股價資料日期
    published_at: pd.Timestamp
    weights: pd.Series  # code -> 權重
    names: pd.Series  # code -> 名稱
    dropped: tuple[str, ...]
    variants: dict[str, tuple[str, ...]] = field(default_factory=dict)  # 實驗名單，例如 ai_filtered

    @property
    def slug(self) -> str:
        return str(self.period)


def to_record(
    picks: MonthlyPicks,
    published_at: pd.Timestamp,
    variants: dict[str, list[str]] | None = None,
    extra: dict | None = None,
) -> dict:
    return {
        "period": str(picks.period),
        "as_of": f"{picks.as_of:%Y-%m-%d}",
        "published_at": published_at.isoformat(timespec="minutes"),
        "picks": [
            {"code": code, "name": str(row["name"]), "weight": round(float(row["weight"]), 6)}
            for code, row in picks.table.iterrows()
        ],
        "dropped": list(picks.dropped.index),
        "variants": {k: list(v) for k, v in (variants or {}).items()},
        **(extra or {}),
    }


def from_record(record: dict) -> PublishedMonth:
    picks = record["picks"]
    return PublishedMonth(
        period=pd.Period(record["period"], freq="M"),
        as_of=pd.Timestamp(record["as_of"]),
        published_at=pd.Timestamp(record["published_at"]),
        weights=pd.Series({p["code"]: p["weight"] for p in picks}, dtype=float),
        names=pd.Series({p["code"]: p["name"] for p in picks}, dtype=object),
        dropped=tuple(record.get("dropped", [])),
        variants={k: tuple(v) for k, v in record.get("variants", {}).items()},
    )


def save_snapshot(
    directory: Path,
    picks: MonthlyPicks,
    body_html: str,
    published_at: pd.Timestamp,
    *,
    variants: dict[str, list[str]] | None = None,
    extra: dict | None = None,
    force: bool = False,
) -> bool:
    """寫入本月封存。已存在就不覆寫（除非 force），回傳是否為新發布。"""
    directory.mkdir(parents=True, exist_ok=True)
    slug = str(picks.period)
    json_path, html_path = directory / f"{slug}.json", directory / f"{slug}.html"
    if json_path.exists() and not force:
        return False
    record = to_record(picks, published_at, variants, extra)
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(body_html, encoding="utf-8")
    return True


def load_published(directory: Path) -> list[PublishedMonth]:
    if not directory.exists():
        return []
    months = [from_record(json.loads(p.read_text(encoding="utf-8"))) for p in directory.glob("*.json")]
    return sorted(months, key=lambda m: m.period)
