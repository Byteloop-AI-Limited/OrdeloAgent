"""Restaurant bot /manage: a one-time restaurant-admin dashboard link, driven through a real Dispatcher offline.

The phone and restaurants come from FakeAdminDb (mimics t_admin_profile); minting is replaced by a recorder so the tests see
exactly which (phone, rest_ref) pairs get a link. mint_dashboard_session_for itself is covered in
tests/watomation/routers/test_rest_admin_auth_session.py.
"""

from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.rest_admin import manage
from config.tgram_setting import TgramBotSettings

from .conftest import message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)
ADA = "447700900101"
APP = "https://restaurant-test.ordelo.app"


async def feed(bot, payload: dict):
    dp = build_rest_admin_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


@pytest.fixture
def minted(monkeypatch):
    """Records mint_dashboard_session_for(phone, rest_ref) calls; set .fail to raise."""
    calls: list[tuple[str, str]] = []

    async def fake_mint(phone, rest_ref):
        if getattr(fake_mint, "fail", False):
            raise RuntimeError("db down")
        calls.append((phone, rest_ref))
        return f"{APP}/rest-admin/activate/tok-{rest_ref}"

    monkeypatch.setattr(manage, "mint_dashboard_session_for", fake_mint)
    fake_mint.calls = calls
    return fake_mint


def sent(session) -> list[SendMessage]:
    return [c for c in session.calls if isinstance(c, SendMessage)]


def link_admin(admin_db, *rests, tuid=111, channels=("telegram",)):
    admin_db.add_admin(ADA, *rests)
    admin_db.record(ADA, tuid=tuid, tcid=tuid, channels=list(channels), t_first_name="Ada")


async def test_a_linked_admin_gets_one_button_per_restaurant_and_no_preview(recording_bot, admin_db, minted):
    link_admin(admin_db, "ELAS", "WREN")
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert minted.calls == [(ADA, "ELAS"), (ADA, "WREN")]
    msg = sent(session)[-1]
    buttons = [b for row in msg.reply_markup.inline_keyboard for b in row]
    assert [(b.text, b.url) for b in buttons] == [
        ("Manage Ela's Kitchen", f"{APP}/rest-admin/activate/tok-ELAS"),
        ("Manage Wren <Cafe>", f"{APP}/rest-admin/activate/tok-WREN"),
    ]
    # The token is used up by a GET: Telegram must not fetch it for a preview, and it stays out of the text.
    assert msg.link_preview_options.is_disabled is True
    assert "activate" not in msg.text and "30 minutes" in msg.text and "works once" in msg.text


async def test_an_admin_on_whatsapp_only_alerts_still_gets_the_link(recording_bot, admin_db, minted):
    link_admin(admin_db, "ELAS", channels=("whatsapp",))
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert minted.calls == [(ADA, "ELAS")] and sent(session)[-1].reply_markup is not None


async def test_an_unlinked_chat_is_told_to_start_and_nothing_is_minted(recording_bot, admin_db, minted):
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "/start" in session.sent_texts[-1] and minted.calls == []


async def test_a_linked_number_on_no_list_is_refused(recording_bot, admin_db, minted):
    admin_db.record(ADA, tuid=111, tcid=111, channels=["telegram"])  # linked, but on no restaurant's admins[]
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "isn't on any restaurant's admin list" in session.sent_texts[-1] and minted.calls == []


async def test_another_telegram_account_gets_nothing(recording_bot, admin_db, minted):
    link_admin(admin_db, "ELAS", tuid=111)
    bot, session = recording_bot
    await feed(bot, message_update("/manage", user_id=222))
    assert minted.calls == [] and "/start" in session.sent_texts[-1]


async def test_a_group_chat_is_private_only_with_no_lookup(recording_bot, admin_db, minted):
    link_admin(admin_db, "ELAS")
    payload = message_update("/manage")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Kitchen"}
    bot, session = recording_bot
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."]
    assert admin_db.rpc_names == [] and minted.calls == []


async def test_profile_failure_gets_a_friendly_reply(recording_bot, admin_db, minted):
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "something went wrong" in session.sent_texts[-1] and minted.calls == []


async def test_mint_failure_gets_a_friendly_reply(recording_bot, admin_db, minted):
    link_admin(admin_db, "ELAS")
    minted.fail = True
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "something went wrong" in session.sent_texts[-1]


async def test_a_refused_button_url_falls_back_to_text_without_preview(recording_bot, admin_db, minted):
    link_admin(admin_db, "WREN")
    bot, session = recording_bot

    def refuse_buttons(method):
        if isinstance(method, SendMessage) and method.reply_markup is not None:
            return TelegramBadRequest(method=method, message="Bad Request: BUTTON_URL_INVALID")
        return None

    session.fail = refuse_buttons
    await feed(bot, message_update("/manage"))
    msg = sent(session)[-1]
    assert msg.reply_markup is None and msg.link_preview_options.is_disabled is True
    assert f"{APP}/rest-admin/activate/tok-WREN" in msg.text and "Wren &lt;Cafe&gt;" in msg.text


async def test_manage_is_in_the_menu_and_help(recording_bot):
    from channels.telegram.rest_admin.commands import HELP_TEXT, REST_ADMIN_COMMANDS

    assert "manage" in [c.command for c in REST_ADMIN_COMMANDS] and "/manage" in HELP_TEXT
