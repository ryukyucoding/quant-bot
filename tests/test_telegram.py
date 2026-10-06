import pytest
import requests

from quant_bot.common import telegram
from quant_bot.common.telegram import TelegramClient, TelegramError, escape, find_chat_ids, split_message

TOKEN = "123456:SECRET-TOKEN"


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append({"url": url, "data": data, "files": files})
        return _Resp({"ok": True, "result": []})

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    return calls


def test_send_message_uses_html_mode(sent):
    TelegramClient(TOKEN, "42").send_message("<b>hi</b>")
    assert sent[0]["url"].endswith("/sendMessage")
    assert sent[0]["data"]["parse_mode"] == "HTML"
    assert sent[0]["data"]["chat_id"] == "42"


def test_long_message_is_split(sent):
    TelegramClient(TOKEN, "42").send_message("\n".join(["x" * 100] * 100))
    assert len(sent) == 3
    assert all(len(c["data"]["text"]) <= telegram.MAX_MESSAGE_CHARS for c in sent)


def test_send_document_attaches_file(sent, tmp_path):
    report = tmp_path / "r.html"
    report.write_text("<p>x</p>", encoding="utf-8")
    TelegramClient(TOKEN, "42").send_document(report, caption="c" * 2000)
    assert sent[0]["files"]["document"][0] == "r.html"
    assert len(sent[0]["data"]["caption"]) == telegram.MAX_CAPTION_CHARS


def test_send_document_missing_file(sent, tmp_path):
    with pytest.raises(TelegramError):
        TelegramClient(TOKEN, "42").send_document(tmp_path / "missing.html")


def test_api_error_is_reported_without_token(monkeypatch):
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _Resp({"ok": False, "description": "chat not found"}))
    with pytest.raises(TelegramError, match="chat not found") as info:
        TelegramClient(TOKEN, "42").send_message("x")
    assert TOKEN not in str(info.value)


def test_connection_error_hides_url_with_token(monkeypatch):
    def boom(url, **_kwargs):
        raise requests.ConnectionError(f"failed to reach {url}")

    monkeypatch.setattr(telegram.requests, "post", boom)
    with pytest.raises(TelegramError) as info:
        TelegramClient(TOKEN, "42").send_message("x")
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_non_json_response(monkeypatch):
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _Resp(ValueError("bad"), status=502))
    with pytest.raises(TelegramError, match="502"):
        TelegramClient(TOKEN, "42").send_message("x")


def test_find_chat_ids_collects_unique_chats(monkeypatch):
    updates = [
        {"message": {"chat": {"id": 42, "first_name": "Yu"}}},
        {"message": {"chat": {"id": 42, "first_name": "Yu"}}},
        {"channel_post": {"chat": {"id": -100, "title": "群組"}}},
        {"edited_message": {}},
    ]
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: _Resp({"ok": True, "result": updates}))
    assert find_chat_ids(TOKEN) == [("42", "Yu"), ("-100", "群組")]


def test_split_message_handles_very_long_line():
    chunks = split_message("a" * 10 + "\n" + "b" * 25, limit=10)
    assert chunks == ["a" * 10, "b" * 10, "b" * 10, "b" * 5]


def test_escape_only_html_specials():
    assert escape('A&B <c> "q"') == 'A&amp;B &lt;c&gt; "q"'
