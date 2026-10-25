"""Selected Telegram handlers opt into durable update deduplication."""

from __future__ import annotations

import asyncio
import inspect

import pytest
from aiogram.types import Update
from aiogram.filters.callback_data import CallbackData

from channels.telegram import inbox
from channels.telegram import callbacks
from channels.telegram.bots import build_rest_admin_dispatcher
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, contact_update, message_update

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)


async def feed(bot, dp, payload: dict):
    return await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def event(update_id: int) -> Update:
    return Update.model_validate(message_update("x", update_id=update_id))


def test_callback_families_have_an_explicit_inbox_policy():
    """A new callback family needs a conscious protected/unprotected decision."""
    protected = {"OrderAction", "RiderSignup", "RiderOffer", "RiderJobAction", "RiderPause", "AdminPause", "AdminChannels"}
    # InviteDecision is retired (TRANSITION, P3 removes): a tap writes nothing any more, so neither y nor n is protected.
    conditional = {"InviteDecision": {"y": False, "n": False}}
    actual = {
        name for name, value in vars(callbacks).items()
        if inspect.isclass(value) and issubclass(value, CallbackData) and value.__module__ == callbacks.__name__
    }
    assert actual == protected | conditional.keys()


async def test_claim_new_then_duplicate(inbox_db):
    assert await inbox.claim("rest_admin", 7, "message", 111) is True
    assert await inbox.claim("rest_admin", 7, "message", 111) is False
    assert inbox_db.rpc_names == ["t_inbox_claim", "t_inbox_claim"]


async def test_claim_is_per_bot(inbox_db):
    assert await inbox.claim("rest_admin", 7, "message", 111) is True
    assert await inbox.claim("rider", 7, "message", 111) is True


async def test_claim_rejects_unexpected_rpc_shape(monkeypatch):
    class Bad:
        def rpc(self, name, args=None):
            return type("Q", (), {"execute": lambda s: type("R", (), {"data": None})()})()

    monkeypatch.setattr("channels.telegram.inbox.client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await inbox.claim("rest_admin", 7, "message", 111)


async def test_finish_only_closes_processing_rows(inbox_db):
    await inbox.claim("rest_admin", 7, "message", 111)
    assert await inbox.finish("rest_admin", 7, "done") == "ok"
    assert await inbox.finish("rest_admin", 7, "failed", "late") == "not_processing"
    assert inbox_db.status_of(7) == "done"


async def test_protected_admin_link_redelivery_runs_once_across_dispatchers(recording_bot, inbox_db, admin_db, invite_db):
    bot, session = recording_bot
    admin_db.add_admin("447700900111")
    payload = contact_update("447700900111", update_id=41)
    await feed(bot, build_rest_admin_dispatcher(SETTINGS), payload)
    await feed(bot, build_rest_admin_dispatcher(SETTINGS), payload)
    assert admin_db.rpc_names == ["t_admin_link"]
    assert inbox_db.rpc_names == ["t_inbox_claim", "t_inbox_finish", "t_inbox_claim"]
    assert inbox_db.rows[("rest_admin", 41)]["kind"] == "message"
    assert inbox_db.rows[("rest_admin", 41)]["tuid"] == 111
    assert inbox_db.status_of(41) == "done"
    assert len(session.sent_texts) == 1


async def test_protected_channel_tap_redelivery_runs_once(recording_bot, inbox_db, admin_db):
    bot, session = recording_bot
    admin_db.add_admin("447700900111")
    admin_db.record("447700900111", tuid=111, tcid=111, channels=["telegram"])
    payload = callback_update("ac1:b", update_id=42)
    await feed(bot, build_rest_admin_dispatcher(SETTINGS), payload)
    await feed(bot, build_rest_admin_dispatcher(SETTINGS), payload)
    assert admin_db.rpc_names.count("admin_set_channels") == 1
    assert inbox_db.status_of(42) == "done"


async def test_read_only_fallback_and_unmatched_updates_have_no_inbox_calls(recording_bot, inbox_db, invite_db):
    bot, session = recording_bot
    dp = build_rest_admin_dispatcher(SETTINGS)
    await feed(bot, dp, message_update("/help", update_id=50))
    await feed(bot, dp, message_update("/help", update_id=50))
    await feed(bot, dp, message_update("/start", update_id=55))
    await feed(bot, dp, message_update("/whoami", update_id=56))
    await feed(bot, dp, message_update("/scratchpad", update_id=57))
    await feed(bot, dp, message_update("hello", update_id=51))
    await feed(bot, dp, callback_update("nope", update_id=52))
    await feed(bot, dp, callback_update("inv:CODE12345678:n", update_id=53))
    sticker = message_update("x", update_id=54)
    sticker["message"].pop("text")
    sticker["message"]["sticker"] = {
        "file_id": "f", "file_unique_id": "u", "type": "regular", "width": 1, "height": 1,
        "is_animated": False, "is_video": False,
    }
    await feed(bot, dp, sticker)
    assert len(session.sent_texts) >= 3
    assert inbox_db.rpc_names == []


async def test_handler_exception_marks_failed_and_retry_is_skipped(inbox_db):
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("kaput")

    with pytest.raises(RuntimeError, match="kaput"):
        await inbox.process_once("rest_admin", event(70), 111, boom)
    await inbox.process_once("rest_admin", event(70), 111, boom)
    assert calls == [1]
    assert inbox_db.status_of(70) == "failed"
    assert "kaput" in inbox_db.rows[("rest_admin", 70)]["error"]


async def test_timeout_cancellation_marks_failed(inbox_db):
    async def slow():
        await asyncio.sleep(5)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(inbox.process_once("rest_admin", event(72), 111, slow), timeout=0.05)
    assert inbox_db.status_of(72) == "failed"
    assert "CancelledError" in inbox_db.rows[("rest_admin", 72)]["error"]


async def test_claim_failure_fails_open(inbox_db):
    inbox_db.fail_claim = True
    calls = []

    async def work():
        calls.append(1)

    await inbox.process_once("rest_admin", event(80), 111, work)
    assert calls == [1]
    assert inbox_db.rows == {}
    assert inbox_db.rpc_names == ["t_inbox_claim"]


async def test_finish_failure_is_swallowed(inbox_db):
    inbox_db.fail_finish = True

    async def work():
        return "handled"

    assert await inbox.process_once("rest_admin", event(81), 111, work) == "handled"
    assert inbox_db.status_of(81) == "processing"
