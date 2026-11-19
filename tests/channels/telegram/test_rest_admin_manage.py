"""Restaurant bot /manage, /sysadmin and the System dashboard button, driven through a real Dispatcher offline.

The roster, overwatch membership and the mint RPCs come from FakeAdminDb (mimics t_admin_profile, portal_access,
rest_admin_dashboard_mint and sys_admin_dashboard_mint); ordelo/dashboard_links.py runs for real on top of it, so the tests
see exactly which (role, phone, rest_ref) got a link and what the buttons carry. The SQL side is proven in
tests/sql/test_admin_dashboard_sql.py; dashboard_links itself in tests/ordelo/test_dashboard_links.py.
"""

from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMyCommands, SendMessage, SetMyCommands
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from config.tgram_setting import TgramBotSettings
from tests.fixtures.fake_admin_db import DASHBOARD_APP as APP

from .conftest import callback_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin",
    {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"},
)
ADA = "447700900101"


async def feed(bot, payload: dict):
    dp = build_rest_admin_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def sent(session) -> list[SendMessage]:
    return [c for c in session.calls if isinstance(c, SendMessage)]


def buttons(msg):
    return [b for row in msg.reply_markup.inline_keyboard for b in row]


def link_admin(admin_db, *rests, tuid=111, channels=("telegram",), ops=False):
    if rests:
        admin_db.add_admin(ADA, *rests)
    admin_db.record(ADA, tuid=tuid, tcid=tuid, channels=list(channels), t_first_name="Ada")
    if ops:
        admin_db.overwatch.add(ADA)


# ---- /manage ----------------------------------------------------------------------------------------------------------
async def test_a_linked_admin_gets_one_button_per_restaurant_and_no_preview(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", "WREN")
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert admin_db.minted == [("rest_admin", ADA, "ELAS"), ("rest_admin", ADA, "WREN")]
    msg = sent(session)[-1]
    got = [(b.text, b.url.rsplit("/", 1)[0]) for b in buttons(msg)]
    assert got == [("Manage Ela's Kitchen", f"{APP}/rest-admin/activate"), ("Manage Wren <Cafe>", f"{APP}/rest-admin/activate")]
    assert msg.link_preview_options.is_disabled is True
    assert "activate" not in msg.text and "30 minutes" in msg.text and "works once" in msg.text
    assert not any(b.callback_data for b in buttons(msg))  # not overwatch: no System dashboard button


async def test_overwatch_admin_also_gets_the_system_dashboard_button_and_scoped_menu(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    b = buttons(sent(session)[-1])
    assert [x.text for x in b] == ["Manage Ela's Kitchen", "System dashboard"] and b[1].callback_data == "sa1:go"
    assert ("sys_admin", ADA, None) not in admin_db.minted  # minted only when the button is tapped
    menu = [c for c in session.calls if isinstance(c, SetMyCommands)][-1]
    assert "sysadmin" in [c.command for c in menu.commands] and menu.scope.chat_id == 111


async def test_ordinary_admin_menu_override_is_cleared(recording_bot, admin_db):
    link_admin(admin_db, "ELAS")
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert any(isinstance(c, DeleteMyCommands) for c in session.calls)
    assert not any(isinstance(c, SetMyCommands) for c in session.calls)


async def test_overwatch_member_with_no_restaurant_gets_only_the_system_button(recording_bot, admin_db):
    link_admin(admin_db, ops=True)
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    msg = sent(session)[-1]
    assert "don't admin a restaurant" in msg.text and [x.text for x in buttons(msg)] == ["System dashboard"]
    assert admin_db.minted == []


async def test_an_admin_on_whatsapp_only_alerts_still_gets_the_link(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", channels=("whatsapp",))
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert admin_db.minted == [("rest_admin", ADA, "ELAS")] and sent(session)[-1].reply_markup is not None


async def test_an_unlinked_chat_is_told_to_start_and_nothing_is_minted(recording_bot, admin_db):
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "/start" in session.sent_texts[-1] and admin_db.minted == []


async def test_a_linked_number_on_no_list_is_refused(recording_bot, admin_db):
    link_admin(admin_db)  # linked, but on no restaurant's admins[] and not overwatch
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "isn't on any restaurant's admin list" in session.sent_texts[-1] and admin_db.minted == []


async def test_another_telegram_account_gets_nothing(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", tuid=111)
    bot, session = recording_bot
    await feed(bot, message_update("/manage", user_id=222))
    assert admin_db.minted == [] and "/start" in session.sent_texts[-1]


async def test_a_group_chat_is_private_only_with_no_lookup(recording_bot, admin_db):
    link_admin(admin_db, "ELAS")
    payload = message_update("/manage")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Kitchen"}
    bot, session = recording_bot
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."]
    assert admin_db.rpc_names == [] and admin_db.minted == []


async def test_store_failure_gets_a_friendly_reply(recording_bot, admin_db):
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, message_update("/manage"))
    assert "something went wrong" in session.sent_texts[-1] and admin_db.minted == []


async def test_a_refused_button_url_falls_back_to_text_without_preview(recording_bot, admin_db):
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
    assert f"{APP}/rest-admin/activate/" in msg.text and "Wren &lt;Cafe&gt;" in msg.text


async def test_manage_is_in_the_menu_and_help(recording_bot):
    from channels.telegram.rest_admin.commands import HELP_TEXT, REST_ADMIN_COMMANDS

    assert "manage" in [c.command for c in REST_ADMIN_COMMANDS] and "/manage" in HELP_TEXT
    assert "sysadmin" not in [c.command for c in REST_ADMIN_COMMANDS]  # never in the published default


# ---- /sysadmin and the System dashboard button -------------------------------------------------------------------------
async def test_sysadmin_sends_one_link_to_an_overwatch_member(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    bot, session = recording_bot
    await feed(bot, message_update("/sysadmin"))
    msg = sent(session)[-1]
    (b,) = buttons(msg)
    assert b.text == "Open system dashboard" and b.url.startswith(f"{APP}/sys-admin/activate/")
    assert msg.link_preview_options.is_disabled is True and "activate" not in msg.text
    assert admin_db.minted == [("sys_admin", ADA, None)]


async def test_sysadmin_refuses_an_ordinary_admin_and_clears_the_menu(recording_bot, admin_db):
    link_admin(admin_db, "ELAS")
    bot, session = recording_bot
    await feed(bot, message_update("/sysadmin"))
    assert "operations only" in session.sent_texts[-1] and admin_db.minted == []
    assert any(isinstance(c, DeleteMyCommands) for c in session.calls)


async def test_sysadmin_unlinked_is_told_to_start(recording_bot, admin_db):
    bot, session = recording_bot
    await feed(bot, message_update("/sysadmin"))
    assert "/start" in session.sent_texts[-1]


async def test_sysadmin_in_a_group_is_private_only(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    payload = message_update("/sysadmin")
    payload["message"]["chat"] = {"id": -100, "type": "supergroup", "title": "Ops"}
    bot, session = recording_bot
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."] and admin_db.minted == []


async def test_system_dashboard_tap_mints_for_the_tapping_person(recording_bot, admin_db):
    link_admin(admin_db, ops=True)
    bot, session = recording_bot
    await feed(bot, callback_update("sa1:go"))
    assert session.answers  # the tap is acknowledged
    assert buttons(sent(session)[-1])[0].url.startswith(f"{APP}/sys-admin/activate/")
    assert admin_db.minted == [("sys_admin", ADA, None)]


async def test_an_old_system_button_after_removal_from_overwatch_gets_nothing(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    admin_db.overwatch.clear()
    bot, session = recording_bot
    await feed(bot, callback_update("sa1:go"))
    assert "operations only" in session.sent_texts[-1] and admin_db.minted == []


async def test_sysadmin_store_failure_is_friendly_and_logs_no_url(recording_bot, admin_db):
    link_admin(admin_db, ops=True)
    admin_db.fail = True
    bot, session = recording_bot
    await feed(bot, message_update("/sysadmin"))
    assert "something went wrong" in session.sent_texts[-1]


# ---- capability menu and help -----------------------------------------------------------------------------------------
async def test_help_lists_sysadmin_only_for_overwatch(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    bot, session = recording_bot
    await feed(bot, message_update("/help"))
    assert "/sysadmin" in session.sent_texts[-1] and "/manage" in session.sent_texts[-1]
    admin_db.overwatch.clear()
    await feed(bot, message_update("/help", update_id=3))
    assert "/sysadmin" not in session.sent_texts[-1]


async def test_ops_only_menu_has_no_restaurant_commands(recording_bot, admin_db):
    link_admin(admin_db, ops=True)
    bot, session = recording_bot
    await feed(bot, message_update("/help"))
    menu = [c for c in session.calls if isinstance(c, SetMyCommands)][-1]
    assert [c.command for c in menu.commands] == ["start", "sysadmin", "help", "whoami"]
    assert "/manage" not in session.sent_texts[-1]


async def test_menu_failure_never_fails_the_command(recording_bot, admin_db):
    link_admin(admin_db, "ELAS", ops=True)
    bot, session = recording_bot

    def refuse_menus(method):
        if isinstance(method, (SetMyCommands, DeleteMyCommands)):
            return TelegramBadRequest(method=method, message="Bad Request: nope")
        return None

    session.fail = refuse_menus
    await feed(bot, message_update("/manage"))
    assert buttons(sent(session)[-1])[0].text == "Manage Ela's Kitchen"
