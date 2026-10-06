"""月報：回測 → 報告 →（選用）封存、建站、推播。台股與美股共用。

  uv run python scripts/monthly_report.py                          產生 reports/（本機檢視）
  uv run python scripts/monthly_report.py --site                   並產生公開網站 site/（含美股研究頁）
  uv run python scripts/monthly_report.py --publish tw --site --notify   台股每月例行（11 日）

輸出：
  reports/<市場>_monthly.html   單檔完整報告（本機開啟、Telegram 附件）
  reports/<市場>_summary.json   數字摘要
  published/                     已發布名單，凍結後不再修改（進 git）
  site/                          公開網站
"""
import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from quant_bot.common.config import load_config, require
from quant_bot.common.metrics import relative_to
from quant_bot.common.portfolio import summarize_window
from quant_bot.common.telegram import TelegramClient
from quant_bot.web.archive import load_published, save_snapshot
from quant_bot.web.notify import format_monthly_message
from quant_bot.web.report import ReportData, render
from quant_bot.web.research import load_results, render_research
from quant_bot.web.site import MarketPages, ResearchPage, SiteConfig, StockPages, Variant, build_site, strip_site_markers
from quant_bot.web.track_record import backtest_periods, published_record

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
SKELETON = (
    '<!doctype html>\n<html lang="zh-Hant">\n<head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n<body>\n{body}\n</body>\n</html>\n'
)


@dataclass(frozen=True)
class MarketResult:
    data: ReportData
    prices: pd.DataFrame  # 計算實際發布紀錄用的還原股價
    market_index: pd.Series  # 大盤（含息）
    published_dir: Path
    ready_to_publish: bool  # 本期資料是否已齊全（美股要等本月第一個交易日收盤）
    variants: dict[str, list[str]] = field(default_factory=dict)  # 與正式名單並列追蹤的實驗名單
    snapshot_extra: dict = field(default_factory=dict)  # 一起凍結的附加資料（例如 AI 檢查內容）
    inputs: object = None  # 台股：產生個股查詢頁用


def build_tw(today: pd.Timestamp, with_ai: bool) -> MarketResult:
    from quant_bot.tw import pipeline as tw
    from quant_bot.tw.ai_pipeline import make_client, run_reviews
    from quant_bot.tw.ai_review import filtered_codes
    from quant_bot.tw.web_spec import TW_SPEC

    inputs = tw.load_inputs(ROOT)
    runs = tw.run_all(inputs)
    start = min(run.result.equity.index[0] for run in runs)
    picks = tw.monthly_picks(inputs, today)
    client = make_client(load_config(ROOT / ".env")) if with_ai else None  # 沒有金鑰 = 關鍵字規則
    reviews = run_reviews(client, picks.table, picks.as_of, ROOT / "data" / "tw" / "review") if with_ai else None
    data = ReportData(TW_SPEC, picks, runs, tw.load_benchmarks(ROOT, inputs, start), pd.Timestamp.now(), reviews)
    market_index = pd.read_parquet(ROOT / "data" / "taiex_tr.parquet")["taiex_tr"]
    variants, extra = {}, {}
    if reviews:
        variants = {AI_VARIANT: filtered_codes(list(picks.table.index), reviews)}
        extra = {"ai_reviews": {code: review.to_dict() for code, review in reviews.items()}}
    ready = picks.period == today.to_period("M") - 1  # 上個月營收已過申報期限才發布
    return MarketResult(data, inputs.panel.adj_close, market_index, ROOT / "published", ready, variants, extra, inputs)


BUILDERS = {"tw": build_tw}


def stock_pages(result: MarketResult) -> StockPages:
    from quant_bot.tw.stock_profiles import build_profiles
    from quant_bot.web.stocks import SEARCH_SCRIPT_HASH, render_index, render_stock_page

    published = load_published(result.published_dir)
    reviews = {
        path.stem: json.loads(path.read_text(encoding="utf-8")).get("ai_reviews", {})
        for path in result.published_dir.glob("*.json")
    }
    profiles = build_profiles(result.inputs, result.data.primary, result.data.picks, result.market_index, published, reviews)
    logging.info("stock pages: %d", len(profiles))
    return StockPages(render_index(profiles), {p.code: render_stock_page(p) for p in profiles}, SEARCH_SCRIPT_HASH)


def research_pages() -> tuple[ResearchPage, ...]:
    """美股只放研究結果頁（scripts/us_factor_research.py 的輸出；還沒跑過就略過）。"""
    try:
        results, curves = load_results(ROOT)
    except FileNotFoundError:
        logging.warning("skip US research page: run scripts/us_factor_research.py first")
        return ()
    config = SiteConfig.load(ROOT / "site.config.json")
    body = render_research(results, curves, config.github_url, pd.Timestamp.now())
    return (ResearchPage("us", "美股研究", "us/", body, "美股研究"),)
AI_VARIANT = "risk_filtered"
VARIANT_LABELS = {
    "tw": ("風險篩選版", "「風險篩選版」是實驗名單：正式名單排除新聞與重大訊息檢查標為高風險的股票，其餘等權重。用來檢驗這道檢查有沒有幫助，從第一期起與正式名單並列記錄。"),
}


def write_local_report(key: str, data: ReportData, body: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    plain = strip_site_markers(body)
    (REPORTS / f"{key}_monthly.body.html").write_text(plain, encoding="utf-8")
    (REPORTS / f"{key}_monthly.html").write_text(SKELETON.format(body=plain), encoding="utf-8")
    oos = data.spec.oos_start
    curves = {run.config.name: run.result.equity for run in data.runs} | {b.short: b.equity for b in data.benchmarks}
    summary = {name: {"full": summarize_window(eq, None, None), "oos": summarize_window(eq, oos, None)} for name, eq in curves.items()}
    summary["primary_vs_market"] = relative_to(data.primary.result.equity, data.market.equity)
    summary["picks"] = {"period": str(data.picks.period), "codes": list(data.picks.table.index), "dropped": list(data.picks.dropped.index)}
    (REPORTS / f"{key}_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def market_pages(result: MarketResult, body: str) -> MarketPages:
    published = load_published(result.published_dir)
    primary = result.data.primary.result
    variant = None
    if result.data.spec.key in VARIANT_LABELS:
        label, note = VARIANT_LABELS[result.data.spec.key]
        variant = Variant(AI_VARIANT, label, note, published_record(published, result.prices, result.market_index, AI_VARIANT))
    return MarketPages(
        spec=result.data.spec,
        latest_body=body,
        published=published,
        published_dir=result.published_dir,
        record=published_record(published, result.prices, result.market_index),
        backtest=backtest_periods(primary.equity, primary.holdings, result.market_index),
        variant=variant,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--markets", nargs="+", choices=list(BUILDERS), default=list(BUILDERS))
    parser.add_argument("--publish", nargs="*", choices=sorted(BUILDERS), default=[], help="封存這些市場的本月名單")
    parser.add_argument("--site", action="store_true", help="產生公開網站到 site/（需包含所有市場）")
    parser.add_argument("--notify", action="store_true", help="推播本次「首次發布」的市場")
    parser.add_argument("--force-notify", action="store_true", help="即使已發布過也推播 --publish 指定的市場")
    parser.add_argument("--review", action="store_true", help="執行新聞與重大訊息檢查（台股；--publish tw 時自動執行）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    requested = {*args.markets, *args.publish}
    markets = [key for key in BUILDERS if key in requested]  # 固定順序：台股、美股（導覽列順序）
    if args.site and set(markets) != set(BUILDERS):
        parser.error("--site 需要所有市場的資料（不要搭配 --markets 只選一個）")
    if args.notify or args.force_notify:  # 先檢查設定，避免跑完回測才發現沒填
        env = load_config(ROOT / ".env")
        token, chat_id = require(env, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

    today = pd.Timestamp.today()
    site_config = SiteConfig.load(ROOT / "site.config.json")
    pages, to_notify, results = [], [], {}
    for key in markets:
        result = BUILDERS[key](today, with_ai=args.review or key in args.publish)
        body = render(result.data)
        write_local_report(key, result.data, body)
        if key in args.publish and not result.ready_to_publish:
            logging.info("skip publish %s: 本期資料還沒齊（最新收盤 %s）", key, f"{result.data.picks.as_of:%Y-%m-%d}")
        elif key in args.publish:
            is_new = save_snapshot(
                result.published_dir, result.data.picks, body, result.data.generated_at,
                variants=result.variants, extra=result.snapshot_extra,
            )
            logging.info("publish %s %s: %s", key, result.data.picks.period, "new" if is_new else "already published, kept frozen")
            if args.force_notify or (args.notify and is_new):
                to_notify.append((key, result.data))
        pages.append(market_pages(result, body))
        results[key] = result

    if args.site:
        written = build_site(SITE, site_config, pages, research_pages(), stock_pages(results["tw"]))
        logging.info("site: %d pages -> %s", len(written), SITE)

    for key, data in to_notify:
        url = site_config.page_url(f"{data.spec.site_dir}index.html") or None
        client = TelegramClient(token, chat_id)
        client.send_message(format_monthly_message(data, url))
        client.send_document(REPORTS / f"{key}_monthly.html", caption=f"{data.spec.name} {data.picks.period} 完整報告")
        logging.info("notified Telegram: %s", key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
