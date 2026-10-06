#!/bin/zsh
# 把 site/ 部署到 GitHub Pages（推到 origin 的 gh-pages 分支）。
# gh-pages 只放產生出來的網頁，每次部署整個覆蓋；原始碼與 published/ 封存在 main 分支。
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE="$(git remote get-url origin 2>/dev/null)" || { echo "尚未設定 GitHub remote（git remote add origin ...）" >&2; exit 1; }
[[ -f site/index.html ]] || { echo "site/ 不存在，先執行 scripts/tw_monthly_report.py --site" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -R site/. "$TMP"
cd "$TMP"
git init -q -b gh-pages
git add -A
git -c user.name="quant-bot" -c user.email="quant-bot@users.noreply.github.com" \
  commit -q -m "deploy: $(date '+%Y-%m-%d %H:%M')"
git push -q --force "$REMOTE" gh-pages
echo "已部署到 gh-pages"
