#!/bin/zsh
# 每月例行：更新資料 → 回測 → 封存名單 → 建站並部署 → Telegram 推播。任一步失敗就停止並推播錯誤。
#   scripts/monthly_job.sh tw   台股（每月 11–15 日每天嘗試：營收申報期限 10 日遇週末會順延；
#                               本月已發布就直接結束，資料還沒齊就略過、隔天再試）
set -euo pipefail
cd "$(dirname "$0")/.."
MARKET="${1:-tw}"
mkdir -p logs
LOG="logs/${MARKET}_$(date +%Y-%m-%d).log"
UV="${UV:-$HOME/.local/bin/uv}"

EXPECTED="$(date -v-1m +%Y-%m)"  # 這個月要發布的是上個月的營收
if [[ -f "published/${EXPECTED}.json" ]]; then
  echo "${EXPECTED} 名單已發布，略過" | tee -a "$LOG"
  exit 0
fi

run() { echo "== $*" | tee -a "$LOG"; "$UV" run python "$@" >>"$LOG" 2>&1; }

fetch() {
  case "$MARKET" in
    tw) run scripts/fetch_tw_revenue.py && run scripts/fetch_tw_prices.py && run scripts/fetch_tw_index.py ;;
    *) echo "未知市場 $MARKET" >&2; return 1 ;;
  esac
}

publish() {
  # 封存的名單進 main 分支（公開紀錄的依據），網站推到 gh-pages
  echo "== publish" | tee -a "$LOG"
  git add published
  if ! git diff --cached --quiet; then
    git commit -q -m "publish: ${MARKET} $(date +%Y-%m) 名單" >>"$LOG" 2>&1
  fi
  git push -q origin HEAD >>"$LOG" 2>&1
  scripts/deploy_site.sh >>"$LOG" 2>&1
}

if ! { fetch && run scripts/monthly_report.py --publish "$MARKET" --site --notify && publish; }; then
  "$UV" run python scripts/notify_failure.py "$LOG" >>"$LOG" 2>&1 || true
  exit 1
fi
echo "done" | tee -a "$LOG"
