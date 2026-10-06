"""台股月營收月報：回測 → 報告 →（選用）封存、建站、推播。

  uv run python scripts/tw_monthly_report.py                  只產生 reports/（本機檢視）
  uv run python scripts/tw_monthly_report.py --publish --site 封存本月名單並產生 site/
  uv run python scripts/tw_monthly_report.py --publish --site --notify   每月例行（排程用）

輸出：
  reports/tw_monthly.html    單檔完整報告（本機開啟、Telegram 附件）
  reports/tw_summary.json    數字摘要
  published/YYYY-MM.*        已發布名單（凍結，進 git）
  site/                      公開網站
"""
import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from quant_bot.common.config import load_config, require
from quant_bot.common.metrics import relative_to
from quant_bot.common.telegram import TelegramClient
from quant_bot.tw.archive import load_published, save_snapshot
from quant_bot.tw.notify import format_monthly_message
from quant_bot.tw.pipeline import load_benchmarks, load_inputs, monthly_picks, run_all, summarize_window
from quant_bot.tw.report import ReportData, render
from quant_bot.tw.site import SiteConfig, build_site, strip_site_markers
from quant_bot.tw.track_record import backtest_periods, published_record

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PUBLISHED = ROOT / "published"
SITE = ROOT / "site"
SKELETON = (
    '<!doctype html>\n<html lang="zh-Hant">\n<head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n{body}\n</body>\n</html>\n'
)
OOS_START = pd.Timestamp("2023-01-01")


def write_local_report(data: ReportData, body: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    plain = strip_site_markers(body)
    (REPORTS / "tw_monthly.body.html").write_text(plain, encoding="utf-8")
    (REPORTS / "tw_monthly.html").write_text(SKELETON.format(body=plain), encoding="utf-8")
    curves = {run.config.name: run.result.equity for run in data.runs} | {b.short: b.equity for b in data.benchmarks}
    summary = {
        name: {"full": summarize_window(eq, None, None), "oos": summarize_window(eq, OOS_START, None)}
        for name, eq in curves.items()
    }
    summary["primary_vs_market"] = relative_to(data.primary.result.equity, data.market.equity)
    summary["picks"] = {
        "period": str(data.picks.period),
        "codes": list(data.picks.table.index),
        "dropped": list(data.picks.dropped.index),
    }
    (REPORTS / "tw_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def build_public_site(data: ReportData, body: str, inputs) -> None:
    config = SiteConfig.load(ROOT / "site.config.json")
    published = load_published(PUBLISHED)
    market_index = pd.read_parquet(ROOT / "data" / "taiex_tr.parquet")["taiex_tr"]
    record = published_record(published, inputs.panel.adj_close, market_index)
    backtest = backtest_periods(data.primary.result.equity, data.primary.result.holdings, market_index)
    pages = build_site(SITE, config, body, published, PUBLISHED, record, backtest)
    logging.info("site: %d pages -> %s", len(pages), SITE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true", help="封存本月名單（已封存則略過）")
    parser.add_argument("--site", action="store_true", help="產生公開網站到 site/")
    parser.add_argument("--notify", action="store_true", help="推播到 Telegram（僅在本月首次發布時）")
    parser.add_argument("--force-notify", action="store_true", help="即使已發布過也推播")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    wants_notify = args.notify or args.force_notify
    if wants_notify:  # 先檢查設定，避免跑完回測才發現沒填
        env = load_config(ROOT / ".env")
        token, chat_id = require(env, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

    inputs = load_inputs(ROOT)
    runs = run_all(inputs)
    start = min(run.result.equity.index[0] for run in runs)
    data = ReportData(
        picks=monthly_picks(inputs, pd.Timestamp.today()),
        runs=runs,
        benchmarks=load_benchmarks(ROOT, inputs, start),
        generated_at=pd.Timestamp.now(),
    )
    body = render(data)
    write_local_report(data, body)

    is_new = False
    if args.publish:
        is_new = save_snapshot(PUBLISHED, data.picks, body, data.generated_at)
        logging.info("publish %s: %s", data.picks.period, "new" if is_new else "already published, kept frozen")
    if args.site:
        build_public_site(data, body, inputs)

    if args.force_notify or (args.notify and is_new):
        site_url = SiteConfig.load(ROOT / "site.config.json").page_url("index.html") or env.get("REPORT_URL") or None
        client = TelegramClient(token, chat_id)
        client.send_message(format_monthly_message(data, site_url))
        client.send_document(REPORTS / "tw_monthly.html", caption=f"{data.picks.period} 營收選股完整報告")
        logging.info("notified Telegram")
    elif args.notify:
        logging.info("skip notify: %s already published", data.picks.period)
    return 0


if __name__ == "__main__":
    sys.exit(main())
