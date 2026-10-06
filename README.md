# quant-bot

台股 / 美股 / 加密貨幣的量化研究與自動化工具。

## 目前進度

| 模組 | 狀態 |
|---|---|
| 共用核心：回測引擎、成本模型、績效指標、SVG 圖表 | ✅ |
| 台股月營收選股：資料抓取、因子、策略、回測、月報網頁 | ✅ |
| 月報推播（Telegram 公開頻道）＋每月自動排程 | ✅ |
| 公開網站（GitHub Pages）：本月名單、歷史紀錄、封存 | ✅ |
| 台股新聞與重大訊息檢查（關鍵字規則）＋實驗名單「風險篩選版」 | ✅ |
| 美股因子研究（預先登記 5 組，見 docs/） | ✅ |
| 美股研究：S&P 500 歷史成分股、SEC 財報、6 組策略回測 → 結論是買指數就好（網站 /us/ 研究頁） | ✅ |
| 加密貨幣資金費率掃描器 | ⏳ |

## 使用方式

```bash
uv sync
uv run python scripts/fetch_tw_revenue.py   # 月營收（第一次約 30 分鐘，之後只抓新月份）
uv run python scripts/fetch_tw_prices.py    # 日股價（yfinance）
uv run python scripts/fetch_tw_index.py     # 證交所含息報酬指數（大盤）
uv run python scripts/fetch_us_data.py      # 美股：S&P 500 歷史成分股、SEC 季營收、日股價（需 .env 的 SEC_CONTACT_EMAIL）
uv run python scripts/monthly_report.py     # 兩個市場回測 + 產生 reports/<市場>_monthly.html
uv run pytest --cov=quant_bot               # 測試
```

每月 11 日之後跑一次，就會用上個月的營收產生新名單。

## Telegram 推播

1. Telegram 找 **@BotFather** → `/newbot` → 取得 token
2. `cp .env.example .env`，填入 `TELEGRAM_BOT_TOKEN`
3. 建立公開頻道並把 bot 加為管理員，`TELEGRAM_CHAT_ID` 填頻道帳號（例如 `@tw_revenue_picks`）；頻道連結填進 `site.config.json` 的 `telegram_channel_url`
4. `uv run python scripts/telegram_setup.py --test` 確認收得到
5. `uv run python scripts/monthly_report.py --publish tw --force-notify` 手動推播一次

## 公開網站

```bash
uv run python scripts/monthly_report.py --site               # 產生 site/（不封存）
uv run python scripts/monthly_report.py --publish tw --site  # 封存台股本月名單到 published/ 並產生 site/
uv run python scripts/us_factor_research.py                   # 重跑美股研究（資料更新後；規則不變）
scripts/deploy_site.sh                                        # 推到 GitHub Pages（gh-pages 分支）
```

- `site.config.json`：網站名稱、網址、Telegram 頻道連結（公開資訊，進 git）
- `published/`：每月發布的名單，一旦寫入就不再修改，是「實際發布紀錄」的依據（進 git）
- 網址：台股在根目錄，美股研究頁在 `/us/`
- 網站是純靜態 HTML，不含 JavaScript，CSP 只允許 Google Fonts

## 新聞與重大訊息檢查（台股）

`--publish tw`（或加 `--review`）會對本月入選股逐檔：

1. 抓公開資訊觀測站近 60 天重大訊息（最新 12 則附全文）與 Google 新聞近 30 天標題
2. 用 `src/quant_bot/tw/risk_rules.py` 的關鍵字規則標出風險（none / watch / high），每個風險都附出處
3. 報告頁顯示檢查結果；排除 high 的股票另成實驗名單「風險篩選版」，和正式名單一起凍結、一起記錄實際表現

選用：`.env` 填 `ANTHROPIC_API_KEY` 會改由 Claude 判讀（`tw/ai_review.py`），預設不使用。

## 每月自動執行

```bash
scripts/install_schedule.sh install    # 台股每月 11 日 18:30（睡眠中錯過會在喚醒後補跑）
scripts/install_schedule.sh status
scripts/install_schedule.sh uninstall
```

`scripts/monthly_job.sh` 會更新台股資料 → 回測 → 新聞與重大訊息檢查 → 封存名單 → 建站部署 → 推播；失敗時推播錯誤 log。
log 在 `logs/`。

## 結構

```
src/quant_bot/
  common/   回測引擎、成本、績效指標、價格、Telegram（各市場共用）
  tw/       台股：MOPS 月營收、證交所報酬指數、因子、策略
  us/       美股：S&P 500 歷史成分股、SEC 季營收、策略
  web/      月報頁、網站、封存、實際發布紀錄、推播訊息（依 MarketSpec 產生各市場頁面）
scripts/    資料下載與報告產生的入口
tests/      pytest
data/       快取資料（不進 git）
reports/    產出的報告（不進 git）
```

## 回測設計原則

- 第 M 月營收只在 M+1 月 10 日之後的第一個交易日才使用（不偷看未來）。
- 主策略與對照組在看結果之前就決定；2023 年起為樣本外驗證期。
- 成本：手續費 0.1425%、證交稅 0.3%（賣出）、每邊 0.1% 滑價。
- 已知偏差：MOPS 歷史營收彙總表只列出目前仍存在的公司，yfinance 也沒有下市股票，
  回測有倖存者偏差（偏樂觀）。主策略應與「合格股票全部等權重」比較，兩者偏差相同。
