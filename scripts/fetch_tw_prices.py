"""依月營收資料中出現過的代號下載日價格，存到 data/prices/tw/。需先跑 fetch_tw_revenue.py。"""
import logging
from pathlib import Path

import pandas as pd

from quant_bot.tw.prices import download_panel, save_panel, yahoo_tickers

ROOT = Path(__file__).resolve().parents[1]
START = "2013-01-01"
BENCHMARKS = ["0050.TW"]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    revenue = pd.read_parquet(ROOT / "data" / "tw_revenue.parquet")
    codes = {m: set(g["code"]) for m, g in revenue.groupby("market")}
    panel = download_panel(yahoo_tickers(codes), START, BENCHMARKS)
    save_panel(panel, ROOT / "data" / "prices" / "tw")
    print(f"saved prices: {panel.adj_close.shape[1]} tickers x {panel.adj_close.shape[0]} days")
