"""Telegram 設定小幫手。

步驟：
  1. 在 .env 填好 TELEGRAM_BOT_TOKEN
  2. 在 Telegram 對你的 bot 傳任意一句話（例如 hi）
  3. uv run python scripts/telegram_setup.py          → 列出 chat id
  4. 把 chat id 填進 .env 的 TELEGRAM_CHAT_ID
  5. uv run python scripts/telegram_setup.py --test   → 發一則測試訊息
"""
import argparse
import sys
from pathlib import Path

from quant_bot.common.config import ConfigError, load_config, require
from quant_bot.common.telegram import TelegramClient, TelegramError, find_chat_ids

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", action="store_true", help="發送測試訊息到 TELEGRAM_CHAT_ID")
    args = parser.parse_args()
    config = load_config(ROOT / ".env")
    try:
        if args.test:
            token, chat_id = require(config, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
            TelegramClient(token, chat_id).send_message("✅ quant-bot 已連線，之後每月營收選股會推播到這裡。")
            print("測試訊息已送出，請到 Telegram 確認。")
            return 0
        (token,) = require(config, "TELEGRAM_BOT_TOKEN")
        chats = find_chat_ids(token)
    except (ConfigError, TelegramError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    if not chats:
        print("還沒收到任何訊息。請先在 Telegram 對你的 bot 傳一句話，再執行一次。")
        return 1
    for chat_id, name in chats:
        print(f"chat id: {chat_id}  ({name})")
    print("把上面的 chat id 填進 .env 的 TELEGRAM_CHAT_ID，然後執行 --test。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
