"""Tests for config.tgram_setting (per-bot Telegram settings from agent_env).

Key Functions:
  - test_for_bot_reads_prefixed_keys - only tgram_<bot_key>_* keys are read
  - test_missing_required_settings_fail_fast - missing token/secret raises RuntimeError naming the keys
  - test_build_bot_* - Bot built for valid settings; malformed token raises
  - test_webhook_* - path/url derivation
  - test_secrets_not_in_repr - SecretStr keeps credentials out of logs
"""

from __future__ import annotations

import pytest

from config.tgram_setting import (
    REST_ADMIN_BOT_KEY,
    TgramBotSettings,
    build_bot,
)

ENV = {
    "tgram_rest_admin_bot_token": "123456:ABC-token",
    "tgram_rest_admin_bot_username": "@my_bot",
    "tgram_rest_admin_webhook_secret": "s3cret_-X",
    "tgram_rest_admin_webhook_base_url": "https://example.com/",
    "tgram_rider_bot_token": "999:RIDER",
    "bloop_waa_token": "unrelated",
}


def test_for_bot_reads_prefixed_keys():
    s = TgramBotSettings.for_bot("rest_admin", ENV)
    assert s.bot_key == "rest_admin"
    assert s.bot_token.get_secret_value() == "123456:ABC-token"
    assert s.webhook_secret.get_secret_value() == "s3cret_-X"
    assert s.bot_username == "my_bot"  # '@' stripped
    assert s.webhook_base_url == "https://example.com"  # trailing '/' stripped


def test_other_bots_keys_are_ignored():
    env = {k: v for k, v in ENV.items() if "bot_token" not in k}
    env["tgram_rider_bot_token"] = "999:RIDER"
    with pytest.raises(RuntimeError, match="tgram_rest_admin_bot_token"):
        TgramBotSettings.for_bot("rest_admin", env)


@pytest.mark.parametrize(
    "env, missing",
    [
        ({}, ["tgram_rest_admin_bot_token", "tgram_rest_admin_webhook_secret"]),
        ({"tgram_rest_admin_bot_token": "123456:ABC"}, ["tgram_rest_admin_webhook_secret"]),
        ({"tgram_rest_admin_webhook_secret": "abc"}, ["tgram_rest_admin_bot_token"]),
        ({"tgram_rest_admin_bot_token": "", "tgram_rest_admin_webhook_secret": "abc"}, ["tgram_rest_admin_bot_token"]),
    ],
)
def test_missing_required_settings_fail_fast(env, missing, monkeypatch):
    for k in ("TGRAM_REST_ADMIN_BOT_TOKEN", "TGRAM_REST_ADMIN_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError) as exc:
        TgramBotSettings.for_bot("rest_admin", env)
    for key in missing:
        assert key in str(exc.value)
    assert "abc" not in str(exc.value) and "123456:ABC" not in str(exc.value)  # no secret values in the message


def test_env_vars_fill_gaps(monkeypatch):
    monkeypatch.setenv("TGRAM_REST_ADMIN_BOT_TOKEN", "111:FROM-ENV")
    monkeypatch.setenv("TGRAM_REST_ADMIN_WEBHOOK_SECRET", "envsecret")
    s = TgramBotSettings.for_bot("rest_admin", {})
    assert s.bot_token.get_secret_value() == "111:FROM-ENV"


def test_build_bot_returns_bot():
    bot = build_bot(TgramBotSettings.for_bot("rest_admin", ENV))
    assert bot is not None and bot.id == 123456


def test_build_bot_raises_on_malformed_token():
    env = {**ENV, "tgram_rest_admin_bot_token": "not-a-token"}
    with pytest.raises(RuntimeError, match="malformed bot token"):
        build_bot(TgramBotSettings.for_bot("rest_admin", env))


def test_invalid_webhook_secret_rejected():
    env = {**ENV, "tgram_rest_admin_webhook_secret": "has space"}
    with pytest.raises(RuntimeError, match="tgram_rest_admin_webhook_secret"):
        TgramBotSettings.for_bot("rest_admin", env)


def test_webhook_path_and_url():
    s = TgramBotSettings.for_bot("rest_admin", ENV)
    assert s.path_slug == "rest-admin"
    assert s.webhook_path == "/telegram/rest-admin/webhook"
    assert s.webhook_url == "https://example.com/telegram/rest-admin/webhook"


def test_webhook_url_empty_without_base_url():
    env = {k: v for k, v in ENV.items() if "base_url" not in k}
    assert TgramBotSettings.for_bot("rest_admin", env).webhook_url == ""


def test_secrets_not_in_repr():
    text = repr(TgramBotSettings.for_bot("rest_admin", ENV))
    assert "123456:ABC-token" not in text and "s3cret_-X" not in text


def test_module_level_rest_admin_values_use_stub_env():
    from config import rest_admin_bot, tgram_rest_admin_settings

    assert tgram_rest_admin_settings.bot_key == REST_ADMIN_BOT_KEY == "rest_admin"
    assert rest_admin_bot is not None
