"""下載 2013 年起所有月營收並存成 data/tw_revenue.parquet。"""
import logging
from pathlib import Path

import pandas as pd

from quant_bot.tw.factors import latest_published_period
from quant_bot.tw.mops import load_revenue

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    end = latest_published_period(pd.Timestamp.today())
    periods = pd.period_range("2013-01", end, freq="M")
    df = load_revenue(periods, ROOT / "data" / "raw" / "mops")
    out = ROOT / "data" / "tw_revenue.parquet"
    df.assign(period=df["period"].astype(str)).to_parquet(out)
    print(f"saved {len(df):,} rows, {df['period'].nunique()} months -> {out}")
