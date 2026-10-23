"""The rider bot (@ByteloopRidersBot) onboarding, driven through a real Dispatcher offline (D39-D42).

FakeRiderDb (conftest.py) mimics the t_rider_* SQL functions; the SQL itself is proven in tests/sql/test_rider_onboarding_sql.py.
Scenario rows (telegram-vertification-loop): allowed actor, wrong actor (forwarded contact), repeated /start, relink,
account already linked elsewhere, bad phone, DB down, group chat, stale/foreign choice taps, every callback within 64 bytes.
"""

from __future__ import annotations

import pytest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.callbacks import RiderSignup, fits_callback_limit
from channels.telegram.keyboards import rider_choice_kb
from channels.telegram.rider.commands import RIDER_COMMANDS
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update, contact_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token": "654321:TEST-rider", "tgram_rider_webhook_secret": "abc"})
PHONE = "447700900501"


async def feed(bot, payload: dict):
    dp = build_rider_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def buttons(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def callback_datas(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ---- /start --------------------------------------------------------------------------------------------------------
async def test_start_unlinked_asks_for_the_phone_with_the_contact_button(recording_bot, rider_db):
    bot, session = recording_bot
    await feed(bot, message_update("/start join"))
    assert "Share my phone number" in session.sent_texts[0]
    kb = session.last_keyboard
    assert isinstance(kb, ReplyKeyboardMarkup) and kb.keyboard[0][0].request_contact is True


async def test_start_linked_and_complete_says_welcome_back(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, name="Sam", tuid=111, tcid=111)
    await feed(bot, message_update("/start"))
    assert session.sent_texts == ["✅ You're already linked, Sam.\nYou'll get your rider messages here."]


async def test_start_linked_with_tbd_town_continues_the_sign_up(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, status="inactive", town="TBD", vehicle="TBD", tuid=111, tcid=111)
    await feed(bot, message_update("/start"))
    assert session.sent_texts == ["Which town will you ride in?"]
    assert buttons(session.last_keyboard) == ["Andover", "Salisbury"]


async def test_start_in_a_group_is_refused(recording_bot, rider_db):
    bot, session = recording_bot
    payload = message_update("/start")
    payload["message"]["chat"] = {"id": -100, "type": "group", "title": "x"}
    await feed(bot, payload)
    assert session.sent_texts == ["Please message me in a private chat."]
    assert rider_db.rpc_names == []


async def test_start_when_db_is_down(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.fail = True
    await feed(bot, message_update("/start"))
    assert "something went wrong" in session.sent_texts[0]


# ---- contact share -------------------------------------------------------------------------------------------------
async def test_forwarded_contact_is_refused_and_nothing_is_linked(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    rider_db.add(PHONE)
    await feed(bot, contact_update("+" + PHONE, user_id=111, contact_user_id=222))
    assert "OWN number" in session.sent_texts[0]
    assert rider_db.riders[PHONE]["tuid"] is None and "t_rider_link" not in rider_db.rpc_names


async def test_invalid_contact_skips_inbox(recording_bot, rider_db, inbox_db):
    bot, _ = recording_bot
    await feed(bot, contact_update(PHONE, contact_user_id=222, update_id=311))
    assert inbox_db.rpc_names == []


async def test_verified_contact_and_signup_choice_are_protected(recording_bot, rider_db, ops_alerts, inbox_db):
    bot, _ = recording_bot
    rider_db.add(PHONE, town="TBD", vehicle="TBD")
    contact = contact_update(PHONE, update_id=312)
    await feed(bot, contact)
    await feed(bot, contact)
    choice = callback_update(RiderSignup(s="t", v="Andover").pack(), update_id=313)
    await feed(bot, choice)
    await feed(bot, choice)
    assert rider_db.rpc_names.count("t_rider_link") == 1
    assert rider_db.rpc_names.count("t_rider_set_profile") == 1
    assert inbox_db.rpc_names == ["t_inbox_claim", "t_inbox_finish", "t_inbox_claim"] * 2
    assert inbox_db.status_of(312, "rider") == "done"
    assert inbox_db.status_of(313, "rider") == "done"


async def test_contact_without_user_id_is_refused(recording_bot, rider_db):
    bot, session = recording_bot
    await feed(bot, contact_update(PHONE, contact_user_id=None))
    assert "OWN number" in session.sent_texts[0]
    assert rider_db.rpc_names == []


async def test_existing_rider_links(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    rider_db.add(PHONE, name="Sam")
    await feed(bot, contact_update("+" + PHONE))
    assert session.sent_texts == ["✅ You're linked, Sam.\nYou'll get your rider messages here."]
    assert isinstance(session.sends[-1].reply_markup, ReplyKeyboardRemove)
    assert rider_db.riders[PHONE]["tuid"] == 111 and rider_db.riders[PHONE]["channel"] == "telegram"
    assert ops_alerts == []
    name, args = next((n, a) for n, a in rider_db.rpc_args if n == "t_rider_link")
    assert args == {"p_tuid": 111, "p_tcid": 111, "p_phone": "+" + PHONE, "p_username": "ada", "p_first_name": "Ada"}


async def test_inactive_existing_rider_hears_it_waits_for_activation(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, name="Sam", status="inactive")
    await feed(bot, contact_update(PHONE))
    assert "waiting for activation" in session.sent_texts[0]


async def test_same_person_again(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, name="Sam", tuid=111, tcid=111)
    await feed(bot, contact_update(PHONE))
    assert session.sent_texts[0].startswith("✅ You're already linked, Sam.")


async def test_relink_moves_the_link_and_alerts_ops(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    r = rider_db.add(PHONE, name="Sam", tuid=999, tcid=999)
    r["t_username"] = "old_handle"
    await feed(bot, contact_update(PHONE))
    assert rider_db.riders[PHONE]["tuid"] == 111
    assert session.sent_texts[0].startswith("✅ You're linked, Sam.")
    assert ops_alerts == [f"Rider bot: rider {PHONE} re-linked from Telegram @old_handle to @ada."]


async def test_account_linked_to_another_rider_is_refused_and_alerts_ops(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    rider_db.add("447700900999", tuid=111, tcid=111)
    rider_db.add(PHONE)
    await feed(bot, contact_update(PHONE))
    assert session.sent_texts == ["This Telegram account is already linked to another rider. Please contact Ordelo."]
    assert rider_db.riders[PHONE]["tuid"] is None
    assert len(ops_alerts) == 1 and "…0999" in ops_alerts[0] and "Refused" in ops_alerts[0]


async def test_bad_phone(recording_bot, rider_db):
    bot, session = recording_bot
    await feed(bot, contact_update("12345"))
    assert "doesn't look like" in session.sent_texts[0]


# ---- new rider: register, then town and vehicle --------------------------------------------------------------------
async def test_unknown_phone_registers_then_asks_town_then_vehicle(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    await feed(bot, contact_update(PHONE, first_name="Priya"))
    assert session.sent_texts == ["Welcome, Priya!", "Which town will you ride in?"]
    assert rider_db.riders[PHONE]["status"] == "inactive"
    assert ops_alerts == [f"Rider bot: new sign-up Priya ({PHONE}, Telegram @ada). Status inactive; activate when ready."]
    town_kb = session.last_keyboard
    assert buttons(town_kb) == ["Andover", "Salisbury"]

    await feed(bot, callback_update(callback_datas(town_kb)[1], update_id=4))
    edit = [c for c in session.calls if isinstance(c, EditMessageText)][-1]
    assert edit.text == "Town: <b>Salisbury</b>\nWhat will you ride?"
    assert buttons(edit.reply_markup) == ["bike", "car"]

    await feed(bot, callback_update(callback_datas(edit.reply_markup)[0], update_id=5))
    assert session.edited_texts[-1] == ("✅ Thanks Priya! You're registered for Salisbury (bike).\n"
                                        "Ordelo will activate your account and message you here.")
    assert rider_db.riders[PHONE]["town"] == "Salisbury" and rider_db.riders[PHONE]["vehicle_type"] == "bike"
    assert rider_db.riders[PHONE]["status"] == "inactive"  # only an operator activates (D41)


async def test_no_choices_tells_the_rider_and_ops(recording_bot, rider_db, ops_alerts):
    bot, session = recording_bot
    rider_db.towns = []
    await feed(bot, contact_update(PHONE))
    assert session.sent_texts[-1].startswith("We can't finish sign-ups right now")
    assert any("no towns" in a for a in ops_alerts)


async def test_choice_tap_from_someone_not_linked(recording_bot, rider_db):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderSignup(s="t", v="Salisbury").pack(), user_id=555))
    assert session.edited_texts == ["Please send /start first to link your rider account."]


async def test_choice_no_longer_listed(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, status="inactive", town="TBD", vehicle="TBD", tuid=111, tcid=111)
    await feed(bot, callback_update(RiderSignup(s="t", v="Atlantis").pack()))
    assert session.edited_texts == ["That option isn't available any more. Please pick again."]
    assert session.sent_texts[-1] == "Which town will you ride in?"


async def test_choice_cannot_overwrite_an_operator_set_town(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, town="Salisbury", vehicle="TBD", tuid=111, tcid=111)
    await feed(bot, callback_update(RiderSignup(s="t", v="Andover").pack()))
    assert session.edited_texts[0].startswith("Your town and vehicle are already set (Salisbury, TBD)")


async def test_every_choice_button_fits_callback_limit():
    long_town = "Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch-on-Sea"
    kb = rider_choice_kb("t", ["Salisbury", long_town, "Odd:Name"])
    assert buttons(kb) == ["Salisbury"]  # too long for 64 bytes and ':' values are left out, not sent broken
    assert all(fits_callback_limit(RiderSignup.unpack(d)) for d in callback_datas(kb))


# ---- help, whoami, fallback ----------------------------------------------------------------------------------------
async def test_help_lists_only_rider_commands(recording_bot, rider_db, monkeypatch):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    async def no_job(rider_id):
        return None
    monkeypatch.setattr("channels.telegram.rider.router.rider_shift.inflight_order", no_job)
    await feed(bot, message_update("/help"))
    for c in RIDER_COMMANDS:
        assert f"/{c.command}" in session.sent_texts[0]
    assert "restaurant" not in session.sent_texts[0].lower()


async def test_help_during_inflight_omits_off_and_on(recording_bot, rider_db, monkeypatch):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    async def on_job(rider_id):
        assert rider_id == PHONE
        return "ELAS-ABCD-1"
    monkeypatch.setattr("channels.telegram.rider.router.rider_shift.inflight_order", on_job)
    await feed(bot, message_update("/help"))
    assert "/off" not in session.sent_texts[0] and "/on " not in session.sent_texts[0]


async def test_whoami_shows_ids_and_link(recording_bot, rider_db):
    bot, session = recording_bot
    rider_db.add(PHONE, name="Sam", tuid=111, tcid=111)
    await feed(bot, message_update("/whoami"))
    text = session.sent_texts[0]
    assert "<code>111</code>" in text and PHONE in text and "channel telegram" in text


async def test_text_from_unlinked_person_points_to_start(recording_bot, rider_db):
    bot, session = recording_bot
    await feed(bot, message_update("hello"))
    assert session.sent_texts == ["Please send /start first to link your rider account."]


async def test_text_from_linked_rider_without_a_job_gets_a_fixed_line_not_the_agent(recording_bot, rider_db, monkeypatch):
    # R4: text goes to the rider agent only when the rider has an open job thread (tests/channels/telegram/test_rider_jobs.py)
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)

    async def no_thread(rider_id, touch=True):
        return None

    monkeypatch.setattr("channels.telegram.rider.jobs.rider_threads.active_for_rider", no_thread)
    await feed(bot, message_update("on my way"))
    assert session.sent_texts == ["No active job. Use /job to check, or /help."]
    assert all(isinstance(c, SendMessage) for c in session.calls)
