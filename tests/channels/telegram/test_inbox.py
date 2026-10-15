"""Tests for channels.telegram.inbox: at-most-once handling of Telegram updates (decision D21)."""

from __future__ import annotations

import asyncio

import pytest
from aiogram import Dispatcher, Router
from aiogram.types import Message, Update

from channels.telegram import inbox
from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.inbox import InboxMiddleware
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, message_update

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)


async def feed(bot, dp, payload: dict):
    return await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def probe_dispatcher(handler=None) -> tuple[Dispatcher, list]:
    """A bare Dispatcher with only the inbox middleware and one catch-all message handler."""
    calls: list = []
    router = Router()

    @router.message()
    async def on_message(message: Message):
        calls.append(message.text)
        if handler:
            await handler(message)

    dp = Dispatcher()
    dp.include_router(router)
    dp.update.outer_middleware(InboxMiddleware("rest_admin"))
    return dp, calls


# ---- wrapper functions --------------------------------------------------------------------------


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


# ---- middleware through a real Dispatcher --------------------------------------------------------


async def test_same_update_twice_runs_handler_once(recording_bot, inbox_db):
    bot, session = recording_bot
    dp = build_rest_admin_dispatcher(SETTINGS)
    await feed(bot, dp, message_update("/help", update_id=41))
    await feed(bot, dp, message_update("/help", update_id=41))
    assert len(session.sent_texts) == 1
    assert inbox_db.status_of(41) == "done"
    assert len(inbox_db.rows) == 1


async def test_different_updates_both_run(recording_bot, inbox_db):
    bot, session = recording_bot
    dp = build_rest_admin_dispatcher(SETTINGS)
    await feed(bot, dp, message_update("/help", update_id=41))
    await feed(bot, dp, message_update("/help", update_id=42))
    assert len(session.sent_texts) == 2


async def test_row_records_kind_and_sender(recording_bot, inbox_db):
    bot, _ = recording_bot
    dp = build_rest_admin_dispatcher(SETTINGS)
    await feed(bot, dp, message_update("/help", user_id=4242, update_id=50))
    await feed(bot, dp, callback_update("nope", user_id=9, update_id=51))
    assert inbox_db.rows[("rest_admin", 50)]["kind"] == "message"
    assert inbox_db.rows[("rest_admin", 50)]["tuid"] == 4242
    assert inbox_db.rows[("rest_admin", 51)]["kind"] == "callback_query"
    assert inbox_db.rows[("rest_admin", 51)]["tuid"] == 9


async def test_unmatched_update_still_finishes_done(recording_bot, inbox_db):
    """A photo (no handler matches) is claimed and closed 'done', not left 'processing'."""
    bot, session = recording_bot
    dp = build_rest_admin_dispatcher(SETTINGS)
    payload = message_update("x", update_id=60)
    payload["message"].pop("text")
    payload["message"]["sticker"] = {
        "file_id": "f", "file_unique_id": "u", "type": "regular", "width": 1, "height": 1,
        "is_animated": False, "is_video": False,
    }
    await feed(bot, dp, payload)
    assert session.calls == []
    assert inbox_db.status_of(60) == "done"


async def test_handler_exception_marks_failed_and_propagates(recording_bot, inbox_db):
    bot, _ = recording_bot

    async def boom(message):
        raise RuntimeError("kaput")

    dp, calls = probe_dispatcher(boom)
    with pytest.raises(RuntimeError, match="kaput"):
        await feed(bot, dp, message_update("hi", update_id=70))
    assert calls == ["hi"]
    assert inbox_db.status_of(70) == "failed"
    assert "kaput" in inbox_db.rows[("rest_admin", 70)]["error"]


async def test_failed_update_redelivered_is_not_rerun(recording_bot, inbox_db):
    """At-most-once: a retry of an update that failed is a duplicate, never handled twice."""
    bot, _ = recording_bot

    async def boom(message):
        raise RuntimeError("kaput")

    dp, calls = probe_dispatcher(boom)
    with pytest.raises(RuntimeError):
        await feed(bot, dp, message_update("hi", update_id=71))
    await feed(bot, dp, message_update("hi", update_id=71))
    assert calls == ["hi"]


async def test_timeout_cancellation_marks_failed(recording_bot, inbox_db):
    """The webhook route cancels slow handlers with wait_for; the row must not stay 'processing'."""
    bot, _ = recording_bot

    async def slow(message):
        await asyncio.sleep(5)

    dp, _ = probe_dispatcher(slow)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(feed(bot, dp, message_update("hi", update_id=72)), timeout=0.05)
    assert inbox_db.status_of(72) == "failed"
    assert "CancelledError" in inbox_db.rows[("rest_admin", 72)]["error"]


async def test_claim_failure_fails_open(recording_bot, inbox_db, caplog):
    bot, _ = recording_bot
    inbox_db.fail_claim = True
    dp, calls = probe_dispatcher()
    await feed(bot, dp, message_update("hi", update_id=80))
    assert calls == ["hi"]
    assert inbox_db.rows == {}  # nothing was recorded, so nothing is finished either


async def test_finish_failure_is_swallowed(recording_bot, inbox_db):
    bot, _ = recording_bot
    inbox_db.fail_finish = True
    dp, calls = probe_dispatcher()
    await feed(bot, dp, message_update("hi", update_id=81))  # must not raise
    assert calls == ["hi"]
    assert inbox_db.status_of(81) == "processing"


async def test_update_without_user_is_claimed_with_null_tuid(recording_bot, inbox_db):
    bot, _ = recording_bot
    dp, _ = probe_dispatcher()
    payload = {
        "update_id": 90,
        "channel_post": {"message_id": 1, "date": 1, "chat": {"id": -100, "type": "channel", "title": "c"}, "text": "x"},
    }
    await feed(bot, dp, payload)
    assert inbox_db.rows[("rest_admin", 90)]["tuid"] is None
    assert inbox_db.rows[("rest_admin", 90)]["kind"] == "channel_post"
