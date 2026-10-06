"""每月例行工作失敗時，把 log 最後幾行推播到 Telegram。"""
import sys
from pathlib import Path

from quant_bot.common.config import load_config, require
from quant_bot.common.telegram import TelegramClient, escape

ROOT = Path(__file__).resolve().parents[1]
TAIL_LINES = 15

if __name__ == "__main__":
    log = Path(sys.argv[1])
    tail = "\n".join(log.read_text(encoding="utf-8").splitlines()[-TAIL_LINES:]) if log.exists() else "(no log)"
    token, chat_id = require(load_config(ROOT / ".env"), "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    TelegramClient(token, chat_id).send_message(
        f"⚠️ <b>quant-bot 月報產生失敗</b>\nlog：{escape(log.name)}\n<pre>{escape(tail)}</pre>"
    )
