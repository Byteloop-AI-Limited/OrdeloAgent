"""Tests for the restaurant-admin bot commands, driven through a real Dispatcher offline."""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.callbacks import fits_callback_limit
from channels.telegram.rest_admin.commands import REST_ADMIN_COMMANDS
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, message_update

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)


async def feed(bot, payload: dict):
    dp = build_rest_admin_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


async def test_start_says_not_linked(recording_bot, invite_db):
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    assert len(session.sent_texts) == 1
    assert "isn't linked" in session.sent_texts[0]


async def test_help_lists_only_restaurant_commands(recording_bot):
    bot, session = recording_bot
    await feed(bot, message_update("/help"))
    text = session.sent_texts[0]
    for c in REST_ADMIN_COMMANDS:
        assert f"/{c.command}" in text
    for starter_only in ("/menu", "/invite", "/app", "/format", "/typing"):
        assert starter_only not in text


async def test_whoami_shows_ids_and_escapes_username(recording_bot, invite_db):
    bot, session = recording_bot
    await feed(bot, message_update("/whoami", user_id=4242, username="a<b>c"))
    text = session.sent_texts[0]
    assert "<code>4242</code>" in text and "not linked" in text
    assert "a&lt;b&gt;c" in text and "a<b>c" not in text


async def test_free_text_gets_fallback(recording_bot):
    bot, session = recording_bot
    await feed(bot, message_update("hello there"))
    assert "Try /help" in session.sent_texts[0]


async def test_unknown_command_gets_fallback_not_other_bot(recording_bot):
    bot, session = recording_bot
    await feed(bot, message_update("/invite 447700900123"))
    assert "Try /help" in session.sent_texts[0]


def test_fits_callback_limit_helper():
    from aiogram.filters.callback_data import CallbackData

    class Ok(CallbackData, prefix="ok"):
        ref: str

    assert fits_callback_limit(Ok(ref="x" * 10))


# ---- invite flow ------------------------------------------------------------------------------


async def test_start_with_code_asks_for_confirmation(recording_bot, invite_db):
    code = invite_db.add(rest_ref="WREN")
    bot, session = recording_bot
    await feed(bot, message_update(f"/start {code}"))
    assert "Wren &lt;Cafe&gt;" in session.sent_texts[0]  # restaurant name HTML-escaped
    buttons = [b.callback_data for row in session.last_keyboard.inline_keyboard for b in row]
    assert buttons == [f"inv:{code}:y", f"inv:{code}:n"]
    assert invite_db.invites[code]["status"] == "pending"  # nothing claimed yet


async def test_yes_claims_and_links(recording_bot, invite_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:y", user_id=111, username="ada"))
    row = invite_db.invites[code]
    assert (row["status"], row["uid"], row["cid"], row["username"]) == ("claimed", 111, 111, "ada")
    assert session.edited_texts == ["✅ You've been onboarded successfully."]


async def test_no_leaves_invite_unclaimed(recording_bot, invite_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:n"))
    assert invite_db.invites[code]["status"] == "pending"
    assert "not linked" in session.edited_texts[0]


async def test_second_person_cannot_claim_used_invite(recording_bot, invite_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:y", user_id=1))
    await feed(bot, callback_update(f"inv:{code}:y", user_id=2, update_id=3))
    assert invite_db.invites[code]["uid"] == 1
    assert "already been used" in session.edited_texts[1]


async def test_same_person_pressing_start_again_sees_linked(recording_bot, invite_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:y", user_id=1))
    await feed(bot, message_update(f"/start {code}", user_id=1, update_id=3))
    assert session.sent_texts[-1] == "✅ You're already onboarded."
    await feed(bot, message_update("/start", user_id=1, update_id=4))
    assert "Welcome back" in session.sent_texts[-1] and "ELAS" in session.sent_texts[-1]


@pytest.mark.parametrize("status,phrase", [("expired", "expired"), ("revoked", "cancelled")])
async def test_unusable_invite_messages(recording_bot, invite_db, status, phrase):
    code = invite_db.add(status=status)
    bot, session = recording_bot
    await feed(bot, message_update(f"/start {code}"))
    assert phrase in session.sent_texts[0] and session.last_keyboard is None


async def test_unknown_code_message(recording_bot, invite_db):
    bot, session = recording_bot
    await feed(bot, message_update("/start NOPE"))
    assert "isn't valid" in session.sent_texts[0]


async def test_whoami_reports_link(recording_bot, invite_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:y", user_id=9))
    await feed(bot, message_update("/whoami", user_id=9, update_id=3))
    assert "Ela's Kitchen (ELAS)" in session.sent_texts[-1]


async def test_database_failure_gets_friendly_reply(recording_bot, monkeypatch):
    class Boom:
        def rpc(self, *a, **k):
            raise RuntimeError("db down")

    monkeypatch.setattr("channels.telegram.invites.client_ordelo_service", Boom())
    bot, session = recording_bot
    await feed(bot, message_update("/start ABC123"))
    assert "something went wrong" in session.sent_texts[0]


def test_invite_callback_fits_telegram_limit():
    from channels.telegram.callbacks import InviteDecision

    assert fits_callback_limit(InviteDecision(code="Ab3_xY9kLm0Q", action="y"))  # issued 12-char code
    assert fits_callback_limit(InviteDecision(code="A" * 50, action="n"))  # generous headroom
