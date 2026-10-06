"""美股資料：S&P 500 歷史成分股、SEC 季營收、yfinance 日價格。需在 .env 設定 SEC_CONTACT_EMAIL。

輸出：
  data/us/sp500_history.csv          成分股變動紀錄
  data/us/sec_v2/<CIK>.parquet       各公司財報原始數據（營收、毛利、營業成本、總資產；快取）
  data/us/revenue_quarters.parquet   季營收與因子（ticker, end, filed, revenue, yoy, ...）
  data/us/quality.parquet            毛利 ÷ 總資產（ticker, end, filed, gpa, ...）
  data/prices/us/*.parquet           日價格
"""
import argparse
import logging
from pathlib import Path

import pandas as pd

from quant_bot.common.config import load_config, require
from quant_bot.common.prices import download_panel, save_panel
from quant_bot.us.fundamentals import quarter_features, quarterly_revenue
from quant_bot.us.quality import gross_profitability
from quant_bot.us.sec import SecClient, fetch_rows, load_ticker_map
from quant_bot.us.universe import load_history, tickers_since

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "us"
UNIVERSE_START = pd.Timestamp("2010-01-01")
PRICE_START = "2009-06-01"
BENCHMARKS = ["SPY", "RSP", "BIL"]  # BIL：1–3 個月美國公債 ETF（趨勢濾網的避險部位）


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="重新下載成分股與 SEC 資料（預訂月更時用）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    (email,) = require(load_config(ROOT / ".env"), "SEC_CONTACT_EMAIL")
    client = SecClient(email)

    history = load_history(DATA / "sp500_history.csv", refresh=args.refresh)
    tickers = sorted(tickers_since(history, UNIVERSE_START))
    cik_map = load_ticker_map(client, DATA / "sec_tickers.json", refresh=args.refresh)
    with_cik = [t for t in tickers if t in cik_map]
    logging.info("universe: %d tickers since %s, %d with SEC CIK", len(tickers), UNIVERSE_START.date(), len(with_cik))

    tables, quality = [], []
    for i, ticker in enumerate(with_cik, 1):
        if i % 50 == 0:
            logging.info("SEC %d / %d", i, len(with_cik))
        rows = fetch_rows(client, cik_map[ticker], DATA / "sec_v2", refresh=args.refresh)
        revenue_rows = rows[rows["metric"] == "revenue"].drop(columns="metric")
        feats = quarter_features(quarterly_revenue(revenue_rows))
        if not feats.empty:
            tables.append(feats.assign(ticker=ticker))
        gpa = gross_profitability(rows)
        if not gpa.empty:
            quality.append(gpa.assign(ticker=ticker))
    quarters = pd.concat(tables, ignore_index=True)
    quarters.to_parquet(DATA / "revenue_quarters.parquet")
    gpa_table = pd.concat(quality, ignore_index=True)
    gpa_table.to_parquet(DATA / "quality.parquet")
    logging.info("revenue: %d tickers｜gross profitability: %d tickers", quarters["ticker"].nunique(), gpa_table["ticker"].nunique())

    panel = download_panel({t: [t] for t in tickers}, PRICE_START, BENCHMARKS)
    save_panel(panel, ROOT / "data" / "prices" / "us")
    priced = set(panel.adj_close.columns) - set(BENCHMARKS)
    print(
        f"成分股（{UNIVERSE_START:%Y} 起曾入選）{len(tickers)} 檔｜有 SEC 營收 {quarters['ticker'].nunique()}｜"
        f"有價格 {len(priced)}｜兩者皆有 {len(priced & set(quarters['ticker']))}"
    )


if __name__ == "__main__":
    main()
