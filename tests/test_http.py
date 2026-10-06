import pytest
import requests

from quant_bot.common import http


class _Resp:
    def raise_for_status(self):
        return None


def test_retries_then_succeeds(monkeypatch):
    calls = []

    def flaky(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("dns")
        return _Resp()

    monkeypatch.setattr(http.requests, "get", flaky)
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    assert isinstance(http.get_with_retry("https://example.invalid"), _Resp)
    assert len(calls) == 3


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("slow")))
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    with pytest.raises(requests.Timeout):
        http.get_with_retry("https://example.invalid", max_retries=2)
