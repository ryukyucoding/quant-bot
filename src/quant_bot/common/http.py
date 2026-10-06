"""共用 HTTP：帶 User-Agent、逾時與指數退避重試。"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (quant-bot research)"
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 5
RETRY_BASE_SEC = 5


def get_with_retry(url: str, *, max_retries: int = MAX_RETRIES, base_wait: float = RETRY_BASE_SEC) -> requests.Response:
    """網路不穩時以指數退避重試；仍失敗則拋出最後一次的例外。"""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SEC)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == max_retries - 1:
                raise
            wait = base_wait * 2**attempt
            log.warning("retry %d/%d in %.0fs: %s (%s)", attempt + 1, max_retries, wait, url, exc.__class__.__name__)
            time.sleep(wait)
    raise AssertionError("unreachable")
