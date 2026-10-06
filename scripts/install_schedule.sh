#!/bin/zsh
# 安裝 / 移除每月排程（macOS launchd）。用法：scripts/install_schedule.sh [install|uninstall|status]
#   台股：每月 11 日 18:30
set -euo pipefail
cd "$(dirname "$0")/.."
LABELS=(com.quantbot.tw)
AGENTS="$HOME/Library/LaunchAgents"
case "${1:-install}" in
  install)
    mkdir -p logs "$AGENTS"
    for label in $LABELS; do
      sed "s|__PROJECT_DIR__|$PWD|g" "deploy/$label.plist" > "$AGENTS/$label.plist"
      launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
    done
    echo "已安裝：台股每月 11 日 18:30" ;;
  uninstall)
    for label in $LABELS; do
      launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
      rm -f "$AGENTS/$label.plist"
    done
    echo "已移除排程" ;;
  status)
    for label in $LABELS; do
      echo "== $label"
      launchctl print "gui/$(id -u)/$label" 2>/dev/null | grep -E "state|last exit" || echo "未安裝"
    done ;;
esac
