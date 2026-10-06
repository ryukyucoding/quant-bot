"""日價格（yfinance）：下載、合併同一標的的多個代號、清理錯價、快取成 parquet。各市場共用。

注意：yfinance 沒有大部分已下市股票的資料，回測會有倖存者偏差（結果偏樂觀）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

CHUNK_SIZE = 80
FIELDS = ("adj_close", "close", "volume")
MIN_COVERAGE_RATIO = 0.5  # 有價格的股票數少於中位數一半的日子視為資料異常


@dataclass(frozen=True)
class PricePanel:
    adj_close: pd.DataFrame  # 還原權值收盤價（計算報酬用）
    close: pd.DataFrame  # 原始收盤價（股價門檻、成交值用）
    volume: pd.DataFrame  # 成交股數

    def traded_value(self, window: int) -> pd.DataFrame:
        """近 window 日平均成交金額。"""
        return (self.close * self.volume).rolling(window, min_periods=window // 2).mean()


def merge_by_code(frame: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    """把同一代號的多個 ticker 合併：以資料較多者為主，缺值由另一個補。"""
    merged: dict[str, pd.Series] = {}
    for code, tickers in mapping.items():
        available = [frame[t] for t in tickers if t in frame.columns and frame[t].notna().any()]
        if not available:
            continue
        available.sort(key=lambda s: s.notna().sum(), reverse=True)
        series = available[0]
        for other in available[1:]:
            series = series.combine_first(other)
        merged[code] = series
    return pd.DataFrame(merged)


def _download_chunk(tickers: list[str], start: str) -> pd.DataFrame:
    return yf.download(tickers, start=start, auto_adjust=False, progress=False, threads=True, group_by="column")


def download_panel(mapping: dict[str, list[str]], start: str, extra: list[str]) -> PricePanel:
    """mapping: 代號 -> yahoo tickers；extra: 直接以 ticker 為代號的標的（基準 ETF 等）。"""
    tickers = sorted({t for ts in mapping.values() for t in ts} | set(extra))
    parts: dict[str, list[pd.DataFrame]] = {f: [] for f in FIELDS}
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i : i + CHUNK_SIZE]
        log.info("download %d-%d / %d", i, i + len(chunk), len(tickers))
        raw = _download_chunk(chunk, start)
        if raw.empty:
            continue
        parts["adj_close"].append(raw["Adj Close"])
        parts["close"].append(raw["Close"])
        parts["volume"].append(raw["Volume"])

    full = {f: pd.concat(parts[f], axis=1).sort_index() for f in FIELDS}
    combined_map = {**mapping, **{t: [t] for t in extra}}
    return PricePanel(**{f: merge_by_code(full[f], combined_map) for f in FIELDS})


def save_panel(panel: PricePanel, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for field in FIELDS:
        getattr(panel, field).to_parquet(directory / f"{field}.parquet")


def load_panel(directory: Path) -> PricePanel:
    missing = [f for f in FIELDS if not (directory / f"{f}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"price cache missing {missing} in {directory}; run the fetch_*_prices script")
    return PricePanel(**{f: pd.read_parquet(directory / f"{f}.parquet") for f in FIELDS})


def drop_reverting_spikes(adj: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """單日跳點（超過門檻、隔天又反向超過門檻）視為錯價，設成 NaN。"""
    filled = adj.ffill()
    jump_in = filled / filled.shift(1) - 1
    jump_out = filled.shift(-1) / filled - 1
    spike = (jump_in.abs() > threshold) & (jump_out.abs() > threshold) & (jump_in * jump_out < 0)
    return adj.mask(spike)


def clean_adjusted(adj_close: pd.DataFrame, spike_threshold: float, clip_limit: float | None = None) -> pd.DataFrame:
    """修正 yfinance 的異常價格。

    1. 移除幾乎沒有股票有報價的日子
    2. 非正價格、單日來回跳點視為錯價
    3. 有漲跌幅限制的市場（clip_limit）把日報酬裁切到限制內，再重建價格序列
    停牌期間以前一個價格延續，報酬計入復牌日。
    """
    coverage = adj_close.notna().sum(axis=1)
    adj = adj_close.loc[coverage >= coverage.median() * MIN_COVERAGE_RATIO]
    adj = adj.where(adj > 0)
    adj = drop_reverting_spikes(adj, spike_threshold)

    returns = adj.ffill().pct_change(fill_method=None)
    if clip_limit is not None:
        returns = returns.clip(-clip_limit, clip_limit)
    rebuilt = (1 + returns.fillna(0)).cumprod()
    first_valid = adj.bfill().iloc[0]
    rebuilt = rebuilt * first_valid  # 保持原本的價格水準，只修正報酬
    return rebuilt.where(adj.ffill().notna())  # 上市前維持 NaN


def clean_panel(panel: PricePanel, spike_threshold: float, clip_limit: float | None = None) -> PricePanel:
    adj = clean_adjusted(panel.adj_close, spike_threshold, clip_limit)
    return PricePanel(adj_close=adj, close=panel.close.reindex(adj.index), volume=panel.volume.reindex(adj.index))
