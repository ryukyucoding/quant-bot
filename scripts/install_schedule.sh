#!/bin/zsh
# 安裝 / 移除每月排程（macOS launchd）。用法：scripts/install_schedule.sh [install|uninstall|status]
set -euo pipefail
cd "$(dirname "$0")/.."
LABEL="com.quantbot.tw-monthly"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
case "${1:-install}" in
  install)
    mkdir -p logs "$HOME/Library/LaunchAgents"
    sed "s|__PROJECT_DIR__|$PWD|g" deploy/$LABEL.plist > "$TARGET"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$TARGET"
    echo "已安裝：每月 11 日 18:30 自動執行" ;;
  uninstall)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$TARGET"
    echo "已移除排程" ;;
  status)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|last exit" || echo "未安裝" ;;
esac
