"""Telegram Bot 推播：文字訊息（HTML 格式）與檔案附件。

注意：Bot API 的網址含有 token，所以所有錯誤都改寫成不含網址的訊息再拋出。
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import requests

API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE_CHARS = 4096
MAX_CAPTION_CHARS = 1024
TIMEOUT_SEC = 30


class TelegramError(RuntimeError):
    pass


def escape(text: str) -> str:
    """Telegram HTML 模式只需要跳脫 & < >。"""
    return html.escape(str(text), quote=False)


def split_message(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """依換行切成不超過 limit 的段落；單行過長則硬切。"""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class TelegramClient:
    token: str
    chat_id: str

    def _call(self, method: str, *, data: dict, files: dict | None = None) -> dict:
        url = API_BASE.format(token=self.token, method=method)
        try:
            resp = requests.post(url, data=data, files=files, timeout=TIMEOUT_SEC)
        except requests.RequestException as exc:
            raise TelegramError(f"{method} 連線失敗（{exc.__class__.__name__}）") from None
        try:
            body = resp.json()
        except ValueError:
            raise TelegramError(f"{method} 回傳非 JSON（HTTP {resp.status_code}）") from None
        if not body.get("ok"):
            raise TelegramError(f"{method} 失敗：{body.get('description', 'unknown error')}")
        return body["result"]

    def send_message(self, text: str) -> None:
        for chunk in split_message(text):
            self._call(
                "sendMessage",
                data={"chat_id": self.chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": "true"},
            )

    def send_document(self, path: Path, caption: str = "") -> None:
        if not path.exists():
            raise TelegramError(f"找不到附件 {path.name}")
        with path.open("rb") as fh:
            self._call(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption[:MAX_CAPTION_CHARS], "parse_mode": "HTML"},
                files={"document": (path.name, fh, "text/html")},
            )


def find_chat_ids(token: str) -> list[tuple[str, str]]:
    """讀取最近傳給 bot 的訊息，回傳 [(chat_id, 名稱)]。設定時用。"""
    client = TelegramClient(token, chat_id="")
    updates = client._call("getUpdates", data={})
    chats: dict[str, str] = {}
    for update in updates:
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat")
        if chat:
            name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            chats[str(chat["id"])] = name or chat.get("username", "")
    return list(chats.items())
