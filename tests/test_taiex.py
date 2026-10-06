import json

import pandas as pd
import pytest

from quant_bot.tw.taiex import fetch_month, parse_month_json

PAYLOAD = {
    "stat": "OK",
    "title": "103年04月 發行量加權股價報酬指數",
    "data": [["103/04/02", "13,157.54"], ["103/04/01", "13,109.80"]],
}


def test_parse_converts_roc_dates_and_numbers():
    series = parse_month_json(PAYLOAD)
    assert list(series.index) == [pd.Timestamp("2014-04-01"), pd.Timestamp("2014-04-02")]
    assert series.iloc[0] == pytest.approx(13109.80)


@pytest.mark.parametrize("payload", [{"stat": "很抱歉，沒有符合條件的資料!"}, {"stat": "OK", "data": []}])
def test_parse_rejects_bad_payload(payload):
    with pytest.raises(ValueError):
        parse_month_json(payload)


def test_completed_month_is_read_from_cache_without_network(tmp_path, monkeypatch):
    (tmp_path / "2014-04.json").write_text(json.dumps(PAYLOAD), encoding="utf-8")

    def no_network(*_args, **_kwargs):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr("quant_bot.tw.taiex.get_with_retry", no_network)
    series = fetch_month(pd.Period("2014-04", "M"), tmp_path, pd.Timestamp("2026-10-06"))
    assert len(series) == 2


def test_current_month_is_refetched_and_not_cached(tmp_path, monkeypatch):
    class Resp:
        def json(self):
            return {"stat": "OK", "data": [["115/10/01", "100,000.00"]]}

    monkeypatch.setattr("quant_bot.tw.taiex.get_with_retry", lambda url: Resp())
    monkeypatch.setattr("quant_bot.tw.taiex.REQUEST_DELAY_SEC", 0)
    series = fetch_month(pd.Period("2026-10", "M"), tmp_path, pd.Timestamp("2026-10-06"))
    assert series.iloc[0] == 100_000
    assert not (tmp_path / "2026-10.json").exists()
