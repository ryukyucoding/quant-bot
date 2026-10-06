#!/bin/zsh
# 每月例行：更新資料 → 回測 → 封存名單 → 建站並部署 → Telegram 推播。任一步失敗就停止並推播錯誤。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
LOG="logs/monthly_$(date +%Y-%m-%d).log"
UV="${UV:-$HOME/.local/bin/uv}"

run() { echo "== $*" | tee -a "$LOG"; "$UV" run python "$@" >>"$LOG" 2>&1; }

publish() {
  # 封存的名單進 main 分支（公開紀錄的依據），網站推到 gh-pages
  echo "== publish" | tee -a "$LOG"
  git add published
  if ! git diff --cached --quiet; then
    git commit -q -m "publish: $(date +%Y-%m) 名單" >>"$LOG" 2>&1
  fi
  git push -q origin HEAD >>"$LOG" 2>&1
  scripts/deploy_site.sh >>"$LOG" 2>&1
}

if ! { run scripts/fetch_tw_revenue.py && run scripts/fetch_tw_prices.py && run scripts/fetch_tw_index.py \
       && run scripts/tw_monthly_report.py --publish --site --notify && publish; }; then
  "$UV" run python scripts/notify_failure.py "$LOG" >>"$LOG" 2>&1 || true
  exit 1
fi
echo "done" | tee -a "$LOG"
