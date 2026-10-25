"""Tests for the restaurant-admin bot commands, driven through a real Dispatcher offline."""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.callbacks import fits_callback_limit
from channels.telegram.rest_admin.commands import REST_ADMIN_COMMANDS
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, contact_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")  # protected handlers claim through the inbox

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)


async def feed(bot, payload: dict):
    dp = build_rest_admin_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


ADA = "447700900101"


def keyboard_has_contact_button(session) -> bool:
    kb = session.last_keyboard
    return bool(kb and any(getattr(b, "request_contact", False) for row in kb.keyboard for b in row))


async def test_start_unlinked_asks_for_the_phone_with_the_share_button(recording_bot, invite_db, admin_db):
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    assert len(session.sent_texts) == 1 and "Share my phone number" in session.sent_texts[0]
    assert keyboard_has_contact_button(session)
    assert admin_db.rpc_names == ["t_admin_profile"]


async def test_start_in_a_group_is_private_only(recording_bot, invite_db, admin_db):
    bot, session = recording_bot
    payload = message_update("/start")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Kitchen"}
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."] and admin_db.rpc_names == []


async def test_start_for_a_linked_admin_shows_restaurants_and_channels(recording_bot, invite_db, admin_db):
    admin_db.add_admin(ADA, "ELAS", "WREN")
    admin_db.record(ADA, tuid=111, tcid=111, channels=["telegram"], t_first_name="Ada")
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    text = session.sent_texts[0]
    assert "already linked" in text and "Ela&#x27;s" not in text and "Ela's Kitchen (ELAS)" in text
    assert "Wren &lt;Cafe&gt; (WREN)" in text and "<b>Telegram</b>" in text and "/channels" in text


async def test_start_for_a_removed_admin_says_so(recording_bot, invite_db, admin_db):
    admin_db.record(ADA, tuid=111, tcid=111, channels=["telegram"])  # on no restaurant's list
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    assert "isn't on any restaurant's admin list" in session.sent_texts[0]


async def test_start_for_an_old_invite_admin_asks_them_to_share_once(recording_bot, invite_db, admin_db):
    code = invite_db.add()
    invite_db.invites[code].update(status="claimed", uid=111, cid=111)
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    assert "old invite link" in session.sent_texts[0] and keyboard_has_contact_button(session)


async def test_start_with_an_old_invite_code_says_invites_are_retired_and_claims_nothing(recording_bot, invite_db, admin_db):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, message_update(f"/start {code}"))
    assert "Invite links aren't used any more" in session.sent_texts[0] and keyboard_has_contact_button(session)
    assert invite_db.invites[code]["status"] == "pending"
    assert "t_claim_invite" not in invite_db.rpc_names and "t_invite_preview" not in invite_db.rpc_names


async def test_start_with_the_fixed_admin_payload_is_the_normal_prompt(recording_bot, invite_db, admin_db):
    bot, session = recording_bot
    await feed(bot, message_update("/start admin"))
    assert "Share my phone number" in session.sent_texts[0] and "Invite links" not in session.sent_texts[0]


async def test_database_failure_on_start_gets_friendly_reply(recording_bot, invite_db, admin_db):
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, message_update("/start"))
    assert "something went wrong" in session.sent_texts[0]


async def test_help_lists_only_restaurant_commands(recording_bot):
    bot, session = recording_bot
    await feed(bot, message_update("/help"))
    text = session.sent_texts[0]
    for c in REST_ADMIN_COMMANDS:
        assert f"/{c.command}" in text
    for starter_only in ("/menu", "/invite", "/app", "/format", "/typing"):
        assert starter_only not in text


async def test_whoami_shows_ids_and_escapes_username(recording_bot, invite_db, admin_db):
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


# ---- contact share ---------------------------------------------------------------------------


async def test_a_verified_contact_links_and_moves_alerts_to_telegram_only(recording_bot, invite_db, admin_db, ops_alerts):
    admin_db.add_admin(ADA, "ELAS")
    bot, session = recording_bot
    await feed(bot, contact_update("+44 7700 900101"))
    assert admin_db.rpc_args[-1] == ("t_admin_link", {"p_tuid": 111, "p_tcid": 111, "p_phone": "+44 7700 900101",
                                                     "p_username": "ada", "p_first_name": "Ada"})
    assert "You're linked" in session.sent_texts[0] and "<b>Telegram</b>" in session.sent_texts[0]
    assert admin_db.records[ADA]["channels"] == ["telegram"] and ops_alerts == []  # a plain link raises no ops alert


async def test_the_same_person_sharing_again_is_already_linked_with_no_alert(recording_bot, invite_db, admin_db, ops_alerts):
    admin_db.add_admin(ADA)
    bot, session = recording_bot
    await feed(bot, contact_update(ADA))
    await feed(bot, contact_update(ADA, update_id=4))
    assert "already linked" in session.sent_texts[-1] and ops_alerts == []


async def test_a_forwarded_or_foreign_contact_is_refused_without_any_rpc(recording_bot, invite_db, admin_db, inbox_db):
    admin_db.add_admin(ADA)
    bot, session = recording_bot
    await feed(bot, contact_update(ADA, contact_user_id=222))
    await feed(bot, contact_update(ADA, contact_user_id=None, update_id=4))
    assert all("OWN number" in t for t in session.sent_texts) and len(session.sent_texts) == 2
    assert admin_db.rpc_names == [] and ADA not in admin_db.records


async def test_a_number_on_no_list_is_refused_and_ops_is_told(recording_bot, invite_db, admin_db, ops_alerts):
    bot, session = recording_bot
    await feed(bot, contact_update("447700900199"))
    assert "isn't set up as a restaurant admin" in session.sent_texts[0]
    assert len(ops_alerts) == 1 and "…0199" in ops_alerts[0] and "447700900199" not in ops_alerts[0]


async def test_a_second_number_from_the_same_account_is_refused_and_ops_is_told(recording_bot, invite_db, admin_db, ops_alerts):
    admin_db.add_admin(ADA)
    admin_db.add_admin("447700900102")
    bot, session = recording_bot
    await feed(bot, contact_update(ADA))
    await feed(bot, contact_update("447700900102", update_id=4))
    assert "already linked to another admin" in session.sent_texts[-1]
    assert len(ops_alerts) == 1 and "…0101" in ops_alerts[0]


async def test_a_new_account_taking_over_a_number_tells_ops(recording_bot, invite_db, admin_db, ops_alerts):
    admin_db.add_admin(ADA)
    bot, session = recording_bot
    await feed(bot, contact_update(ADA, user_id=111, contact_user_id=111, username="old"))
    await feed(bot, contact_update(ADA, user_id=222, contact_user_id=222, username="new", update_id=4))
    assert "You're linked" in session.sent_texts[-1]
    assert len(ops_alerts) == 1 and "re-linked from Telegram @old to @new" in ops_alerts[0]


async def test_bad_number_gets_a_helpful_reply(recording_bot, invite_db, admin_db, ops_alerts):
    bot, session = recording_bot
    await feed(bot, contact_update("12345"))
    assert "doesn't look like a mobile number" in session.sent_texts[0] and ops_alerts == []


async def test_link_failure_gets_friendly_reply(recording_bot, invite_db, admin_db):
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, contact_update(ADA))
    assert "something went wrong" in session.sent_texts[0]


async def test_a_redelivered_contact_update_links_once(recording_bot, invite_db, admin_db):
    admin_db.add_admin(ADA)
    bot, session = recording_bot
    await feed(bot, contact_update(ADA, update_id=7))
    await feed(bot, contact_update(ADA, update_id=7))
    assert admin_db.rpc_names.count("t_admin_link") == 1


async def test_contact_in_a_group_is_private_only(recording_bot, invite_db, admin_db):
    bot, session = recording_bot
    payload = contact_update(ADA)
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Kitchen"}
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."] and admin_db.rpc_names == []


# ---- whoami ----------------------------------------------------------------------------------------------


async def test_whoami_reports_link_and_channels(recording_bot, invite_db, admin_db):
    admin_db.add_admin(ADA)
    admin_db.record(ADA, tuid=9, tcid=9, channels=["telegram", "whatsapp"])
    bot, session = recording_bot
    await feed(bot, message_update("/whoami", user_id=9))
    text = session.sent_texts[-1]
    assert "Ela's Kitchen (ELAS)" in text and "Telegram and WhatsApp" in text


async def test_whoami_for_an_old_invite_admin_says_to_switch(recording_bot, invite_db, admin_db):
    code = invite_db.add()
    invite_db.invites[code].update(status="claimed", uid=9, cid=9)
    bot, session = recording_bot
    await feed(bot, message_update("/whoami", user_id=9))
    assert "old invite" in session.sent_texts[-1] and "Ela's Kitchen (ELAS)" in session.sent_texts[-1]


# ---- old invite buttons (TRANSITION, P3 removes) ------------------------------------------------------------


@pytest.mark.parametrize("action", ["y", "n"])
async def test_an_old_invite_button_claims_nothing_and_points_at_the_new_link(recording_bot, invite_db, admin_db, action):
    code = invite_db.add()
    bot, session = recording_bot
    await feed(bot, callback_update(f"inv:{code}:{action}", user_id=111))
    assert invite_db.invites[code]["status"] == "pending" and "t_claim_invite" not in invite_db.rpc_names
    assert session.edited_texts == ["Invite links aren't used any more."]
    assert "Share my phone number" in session.sent_texts[-1] and keyboard_has_contact_button(session)


def test_invite_callback_fits_telegram_limit():
    from channels.telegram.callbacks import InviteDecision

    assert fits_callback_limit(InviteDecision(code="Ab3_xY9kLm0Q", action="y"))
    assert fits_callback_limit(InviteDecision(code="A" * 50, action="n"))


async def test_hanging_callback_answer_does_not_block_the_old_invite_reply(recording_bot, invite_db, admin_db, monkeypatch):
    import asyncio

    from aiogram.methods import AnswerCallbackQuery

    from channels.telegram import replies

    monkeypatch.setattr(replies, "CALLBACK_ANSWER_TIMEOUT_SECS", 0.05)
    bot, session = recording_bot
    code = invite_db.add()
    real = session.make_request

    async def make_request(b, method, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            await asyncio.sleep(30)
        return await real(b, method, timeout)

    session.make_request = make_request
    await asyncio.wait_for(feed(bot, callback_update(f"inv:{code}:y", user_id=111, username="ada")), timeout=5)
    assert session.edited_texts == ["Invite links aren't used any more."]
