"""Restaurant bot /channels (plans/restaurant-admin-roster-onboarding-plan.md, D6), driven through a real Dispatcher offline."""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.callbacks import AdminChannels, fits_callback_limit
from channels.telegram.keyboards import CHANNEL_CHOICES, admin_channels_kb
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)
ADA = "447700900201"


async def feed(bot, payload: dict):
    await build_rest_admin_dispatcher(SETTINGS).feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def linked(admin_db, channels=("telegram",)):
    admin_db.add_admin(ADA)
    return admin_db.record(ADA, tuid=111, tcid=111, channels=list(channels), t_first_name="Ada")


async def test_channels_unlinked_asks_for_the_phone(recording_bot, admin_db):
    bot, session = recording_bot
    await feed(bot, message_update("/channels"))
    assert "Share my phone number" in session.sent_texts[0]
    assert any(getattr(b, "request_contact", False) for row in session.last_keyboard.keyboard for b in row)


async def test_channels_linked_shows_current_choice_and_three_buttons(recording_bot, admin_db):
    linked(admin_db, ("telegram", "whatsapp"))
    bot, session = recording_bot
    await feed(bot, message_update("/channels"))
    assert "<b>Telegram and WhatsApp</b>" in session.sent_texts[0]
    assert [b.callback_data for row in session.last_keyboard.inline_keyboard for b in row] == ["ac1:t", "ac1:w", "ac1:b"]


async def test_channels_for_a_removed_admin_says_so(recording_bot, admin_db):
    admin_db.record(ADA, tuid=111, tcid=111, channels=["telegram"])  # on no list
    bot, session = recording_bot
    await feed(bot, message_update("/channels"))
    assert "isn't on any restaurant's admin list" in session.sent_texts[0] and session.last_keyboard is None


async def test_channels_in_a_group_is_private_only(recording_bot, admin_db):
    bot, session = recording_bot
    payload = message_update("/channels")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Kitchen"}
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."] and admin_db.rpc_names == []


@pytest.mark.parametrize("code, expected", [("t", ["telegram"]), ("w", ["whatsapp"]), ("b", ["telegram", "whatsapp"])])
async def test_each_tap_sets_the_right_channels_for_the_tapping_person(recording_bot, admin_db, code, expected):
    rec = linked(admin_db)
    bot, session = recording_bot
    await feed(bot, callback_update(f"ac1:{code}", user_id=111))
    assert rec["channels"] == expected
    assert admin_db.rpc_args[-1] == ("admin_set_channels", {"p_phone": ADA, "p_channels": expected, "p_by": "telegram:111"})
    assert session.edited_texts[0].startswith("✅ Order alerts:")


async def test_a_stranger_tapping_an_old_button_changes_nothing(recording_bot, admin_db):
    rec = linked(admin_db)
    bot, session = recording_bot
    await feed(bot, callback_update("ac1:w", user_id=999))
    assert rec["channels"] == ["telegram"] and "admin_set_channels" not in admin_db.rpc_names
    assert "isn't linked yet" in session.edited_texts[0]


async def test_a_removed_admin_tapping_cannot_change_anything(recording_bot, admin_db):
    rec = admin_db.record(ADA, tuid=111, tcid=111, channels=["telegram"])
    bot, session = recording_bot
    await feed(bot, callback_update("ac1:b", user_id=111))
    assert rec["channels"] == ["telegram"] and "admin_set_channels" not in admin_db.rpc_names
    assert "isn't on any restaurant's admin list" in session.edited_texts[0]


async def test_database_failure_gets_friendly_reply(recording_bot, admin_db):
    linked(admin_db)
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, callback_update("ac1:b", user_id=111))
    assert "something went wrong" in session.edited_texts[0]


async def test_p1_text_says_whatsapp_follows_later_until_the_flag_flips(recording_bot, admin_db, monkeypatch):
    from channels.telegram.rest_admin import channels

    linked(admin_db)
    bot, session = recording_bot
    await feed(bot, message_update("/channels"))
    assert "WhatsApp will follow" in session.sent_texts[0]
    monkeypatch.setattr(channels, "WHATSAPP_FOLLOWS_CHANNELS", True)
    await feed(bot, message_update("/channels", update_id=5))
    assert "WhatsApp will follow" not in session.sent_texts[1]


def test_callbacks_fit_the_telegram_limit_and_every_choice_has_a_button():
    for code in CHANNEL_CHOICES:
        assert fits_callback_limit(AdminChannels(c=code))
    assert len(admin_channels_kb().inline_keyboard) == len(CHANNEL_CHOICES)
