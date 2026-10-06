"""下載證交所發行量加權股價報酬指數（含息大盤），存到 data/taiex_tr.parquet。"""
import logging
from pathlib import Path

import pandas as pd

from quant_bot.tw.taiex import load_total_return_index

ROOT = Path(__file__).resolve().parents[1]
START = "2013-01"

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    series = load_total_return_index(START, ROOT / "data" / "raw" / "taiex", pd.Timestamp.today())
    out = ROOT / "data" / "taiex_tr.parquet"
    series.to_frame().to_parquet(out)
    print(f"saved {len(series):,} days ({series.index[0]:%Y-%m-%d} ~ {series.index[-1]:%Y-%m-%d}) -> {out}")
