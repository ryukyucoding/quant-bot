"""讀取 .env 設定（KEY=VALUE），環境變數優先於檔案。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


KNOWN_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "REPORT_URL", "SEC_CONTACT_EMAIL", "ANTHROPIC_API_KEY")


class ConfigError(RuntimeError):
    pass


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config(env_file: Path, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    file_values = parse_env(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    env = os.environ if environ is None else environ
    overrides = {k: env[k] for k in (*KNOWN_KEYS, *file_values) if env.get(k)}
    return {**file_values, **overrides}


def require(config: Mapping[str, str], *keys: str) -> tuple[str, ...]:
    missing = [k for k in keys if not config.get(k)]
    if missing:
        raise ConfigError(f"缺少設定 {', '.join(missing)}：請在 .env 填入（參考 .env.example）")
    return tuple(config[k] for k in keys)
