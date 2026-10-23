"""Tests for channels.telegram.bots (registry and per-bot Dispatcher construction)."""

from __future__ import annotations

import pytest

from channels.telegram.bots import (
    build_registry,
    build_rest_admin_dispatcher,
    close_registry,
    find_by_slug,
)
from config.tgram_setting import TgramBotSettings

ENV = {
    "tgram_rest_admin_bot_token": "123456:TEST-token",
    "tgram_rest_admin_webhook_secret": "abc",
}


@pytest.fixture
def settings():
    return TgramBotSettings.for_bot("rest_admin", ENV)


def test_dispatchers_get_separate_router_trees(settings):
    """Regression guard for the starter's module-level singleton router/_dp problem."""
    dp1 = build_rest_admin_dispatcher(settings)
    dp2 = build_rest_admin_dispatcher(settings)  # would raise RuntimeError if routers were shared
    assert dp1 is not dp2
    assert dp1.sub_routers[0] is not dp2.sub_routers[0]


def test_registry_and_slug_lookup(settings, recording_bot):
    bot, _ = recording_bot
    registry = build_registry([(settings, bot)])
    assert list(registry) == ["rest_admin"]
    assert find_by_slug(registry, "rest-admin") is registry["rest_admin"]
    assert find_by_slug(registry, "rider") is None
    assert registry["rest_admin"].key == "rest_admin"


async def test_close_registry_closes_sessions(settings, recording_bot):
    bot, session = recording_bot
    await close_registry(build_registry([(settings, bot)]))
    assert session.closed is True


# ---- rider bot ------------------------------------------------------------------------------------------------------
from channels.telegram.bots import build_rider_dispatcher, default_registry  # noqa: E402

RIDER = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token": "654321:TEST-rider", "tgram_rider_webhook_secret": "r"})


def test_rider_dispatchers_get_separate_router_trees():
    dp1, dp2 = build_rider_dispatcher(RIDER), build_rider_dispatcher(RIDER)
    assert dp1.sub_routers[0] is not dp2.sub_routers[0]
    assert dp1.sub_routers[0].name == "rider"


def test_registry_with_both_bots(settings, recording_bot):
    bot, _ = recording_bot
    registry = build_registry([(settings, bot), (RIDER, bot)])
    assert sorted(registry) == ["rest_admin", "rider"]
    assert find_by_slug(registry, "rider") is registry["rider"]
    assert registry["rider"].cards is None and registry["rider"].receipts is None
    assert registry["rider"].dp is not registry["rest_admin"].dp


def test_default_registry_skips_an_unconfigured_rider_bot(monkeypatch):
    import config

    monkeypatch.setattr(config, "tgram_rider_settings", None)
    monkeypatch.setattr(config, "rider_bot", None)
    assert list(default_registry()) == ["rest_admin"]


def test_default_registry_includes_a_configured_rider_bot():
    assert sorted(default_registry()) == ["rest_admin", "rider"]  # tests/conftest.py stubs tgram_rider_* keys
