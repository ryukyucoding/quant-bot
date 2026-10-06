import pytest

from quant_bot.common.config import ConfigError, load_config, parse_env, require


def test_parse_env_ignores_comments_and_strips_quotes():
    text = '# comment\nTELEGRAM_BOT_TOKEN="abc:123"\n\nTELEGRAM_CHAT_ID=42\nBROKEN LINE\n'
    assert parse_env(text) == {"TELEGRAM_BOT_TOKEN": "abc:123", "TELEGRAM_CHAT_ID": "42"}


def test_environment_overrides_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_CHAT_ID=1\nREPORT_URL=\n", encoding="utf-8")
    config = load_config(env_file, environ={"TELEGRAM_CHAT_ID": "2", "UNRELATED": "x"})
    assert config["TELEGRAM_CHAT_ID"] == "2"
    assert "UNRELATED" not in config


def test_missing_file_uses_environment(tmp_path):
    config = load_config(tmp_path / "nope.env", environ={"TELEGRAM_BOT_TOKEN": "t"})
    assert config == {"TELEGRAM_BOT_TOKEN": "t"}


def test_require_reports_all_missing_keys():
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"):
        require({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    assert require({"A": "1"}, "A") == ("1",)
