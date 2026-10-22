"""ordelo/rider_messaging: the RiderMessenger interface, both adapters and the channel choice (D43-D45, D49).

WhatsApp: the adapter must make exactly the pywa calls the agent and hooks make today (byte-identical text, same payload
JSON for offers, verbatim missed-offer text), so phase R3 can switch callers without changing a WhatsApp message.
Telegram: rendering (WhatsApp-style -> HTML), reply threading in the same chat only, reactions, offers with ro1 callbacks,
and offer_closed editing in place with the buttons removed and no new message.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.methods import EditMessageText, SendContact, SendLocation, SendMessage, SendVenue, SetMessageReaction
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from channels.telegram.callbacks import RiderOffer, fits_callback_limit
from ordelo.rider_messaging import (
    ContactCard,
    JobOffer,
    LinkButton,
    Place,
    RiderMessenger,
    messenger_for,
    parse_tg_ref,
    tg_ref,
    use_messenger,
)
from ordelo.rider_messaging.fake import RecordingRiderMessenger
from ordelo.rider_messaging.formatting import TELEGRAM_TEXT_LIMIT, wa_to_html
from ordelo.rider_messaging.telegram import TelegramRiderMessenger
from ordelo.rider_messaging.whatsapp import WhatsAppRiderMessenger, missed_offer_text
from tests.channels.telegram.conftest import RecordingSession

PHONE = "447700900501"
OFFER = JobOffer(dispatch_id=84217, order_number="ELAS-CEKT-22", header="2.1 miles, £4.50, @12:30",
                 text="\n    Pickup time - *12:30*\n\nOrder number - *ELAS-CEKT-22*\n    ")


@pytest.fixture
def recording_bot():
    session = RecordingSession()
    return Bot(token="654321:TEST-rider", session=session), session


# ---- refs ----------------------------------------------------------------------------------------------------------
def test_tg_refs_round_trip_and_reject_others():
    assert parse_tg_ref(tg_ref(-100123, 42)) == (-100123, 42)
    for other in (None, "", "wamid.HBgM", "tg:abc:1", "tg:12"):
        assert parse_tg_ref(other) is None


# ---- WhatsApp: same pywa calls as today ----------------------------------------------------------------------------
@pytest.fixture
def wa():
    client = MagicMock()
    for name in ("send_message", "send_location", "request_location", "send_contact", "send_reaction"):
        setattr(client, name, AsyncMock(return_value=MagicMock(id="wamid.SENT")))
    return client


async def test_wa_say_passes_text_through_and_returns_the_wamid(wa):
    m = WhatsAppRiderMessenger(wa, PHONE)
    ref = await m.say("Heads up *Sam*", reply_to="wamid.PREV")
    assert ref == "wamid.SENT"
    wa.send_message.assert_awaited_once_with(to=PHONE, text="Heads up *Sam*", reply_to_message_id="wamid.PREV")


async def test_wa_say_with_header_and_link_matches_the_live_tracking_call(wa):
    from pywa.types import ButtonUrl

    await WhatsAppRiderMessenger(wa, PHONE).say(
        "Please turn on the live tracking by clicking the link below.", header="Enable Live Tracking",
        reply_to="wamid.R", link=LinkButton("Start live tracking", "https://x/y"))
    wa.send_message.assert_awaited_once_with(
        to=PHONE, text="Please turn on the live tracking by clicking the link below.", reply_to_message_id="wamid.R",
        header="Enable Live Tracking", buttons=ButtonUrl(title="Start live tracking", url="https://x/y"))


async def test_wa_ignores_a_telegram_reply_target(wa):
    await WhatsAppRiderMessenger(wa, PHONE).say("x", reply_to=tg_ref(1, 2))
    assert wa.send_message.await_args.kwargs["reply_to_message_id"] is None


async def test_wa_place_contact_location_request_and_reaction(wa):
    m = WhatsAppRiderMessenger(wa, PHONE)
    await m.send_place(Place(51.07, -1.79, " ", "1 High St"), reply_to="wamid.R")
    wa.send_location.assert_awaited_once_with(to=PHONE, latitude=51.07, longitude=-1.79, name=" ", address="1 High St",
                                              reply_to_message_id="wamid.R")
    await m.request_location("Please share your current location.")
    wa.request_location.assert_awaited_once_with(to=PHONE, text="Please share your current location.")
    await m.send_contact(ContactCard("ELAS-CEKT-22", "447700900777"))
    contact = wa.send_contact.await_args.kwargs["contact"]
    assert contact.name.formatted_name == "ELAS-CEKT-22" and contact.phones[0].wa_id == "447700900777"
    assert contact.phones[0].type == "MOBILE"
    await m.mark("wamid.CODE", ok=False)
    wa.send_reaction.assert_awaited_once_with(to=PHONE, emoji="❌", message_id="wamid.CODE")


async def test_wa_offer_has_todays_payloads(wa):
    await WhatsAppRiderMessenger(wa, PHONE).offer_job(OFFER)
    kw = wa.send_message.await_args.kwargs
    assert (kw["to"], kw["header"], kw["text"], kw["footer"]) == (PHONE, OFFER.header, OFFER.text, "♾️ Byteloop AI")
    accept, decline = (json.loads(b.callback_data) for b in kw["buttons"])
    assert [b.title for b in kw["buttons"]] == ["Accept", "Decline"]
    assert accept == {"command": "/dispatchResponse", "order_number": "ELAS-CEKT-22", "dispatch_id": 84217,
                      "status": "accepted", "rider_id": PHONE}
    assert decline["status"] == "declined"


async def test_wa_offer_closed_sends_todays_text_only_when_taken(wa):
    m = WhatsAppRiderMessenger(wa, PHONE)
    await m.offer_closed("wamid.OFFER", "ELAS-CEKT-22", "expired")
    wa.send_message.assert_not_awaited()
    await m.offer_closed("wamid.OFFER", "ELAS-CEKT-22", "taken")
    wa.send_message.assert_awaited_once_with(to=PHONE, text=missed_offer_text("ELAS-CEKT-22"))


def test_missed_text_is_verbatim_from_the_hook():
    from pathlib import Path

    hook = (Path(__file__).resolve().parents[2] / "watomation" / "routers" / "delivery_hooks.py").read_text()
    assert '''            _text = f"""
            Sorry, the order was picked up by another rider. Order number: *{order_number}*
            """''' in hook
    assert missed_offer_text("X") == "\n            Sorry, the order was picked up by another rider. Order number: *X*\n            "


# ---- Telegram ------------------------------------------------------------------------------------------------------
@pytest.fixture
def tg(recording_bot):
    bot, session = recording_bot
    return TelegramRiderMessenger(bot, 111), session


async def test_tg_say_renders_html_and_threads_in_the_same_chat(tg):
    m, session = tg
    ref = await m.say("Pickup *ELAS-1* at <12:30> & go", reply_to=tg_ref(111, 7), header="Heads up", footer="Byteloop")
    call = session.calls[-1]
    assert isinstance(call, SendMessage)
    assert call.text == "<b>Heads up</b>\nPickup <b>ELAS-1</b> at &lt;12:30&gt; &amp; go\n<i>Byteloop</i>"
    assert call.reply_parameters.message_id == 7
    assert parse_tg_ref(ref) == (111, session.next_message_id)


async def test_tg_reply_to_another_chat_or_whatsapp_is_dropped(tg):
    m, session = tg
    await m.say("a", reply_to=tg_ref(999, 7))
    await m.say("b", reply_to="wamid.X")
    assert all(c.reply_parameters is None for c in session.calls)


async def test_tg_link_button(tg):
    m, session = tg
    await m.say("Track", link=LinkButton("Start live tracking", "https://x/y"))
    kb = session.calls[-1].reply_markup
    assert isinstance(kb, InlineKeyboardMarkup) and kb.inline_keyboard[0][0].url == "https://x/y"


async def test_tg_places(tg):
    m, session = tg
    await m.send_place(Place(51.0, -1.0, "Elas - Pickup", "1 High St"))
    await m.send_place(Place(52.0, -2.0, " ", "2 Low St"))
    assert isinstance(session.calls[0], SendVenue) and session.calls[0].title == "Elas - Pickup"
    assert isinstance(session.calls[1], SendLocation) and session.calls[1].latitude == 52.0


async def test_tg_location_request_uses_the_one_tap_button(tg):
    m, session = tg
    await m.request_location("Please share your current location.")
    kb = session.calls[-1].reply_markup
    assert isinstance(kb, ReplyKeyboardMarkup) and kb.keyboard[0][0].request_location is True


async def test_tg_contact_and_reactions(tg):
    m, session = tg
    await m.send_contact(ContactCard("ELAS-1", "447700900777"))
    assert isinstance(session.calls[-1], SendContact) and session.calls[-1].phone_number == "447700900777"
    await m.mark(tg_ref(111, 5), ok=True)
    await m.mark(tg_ref(111, 6), ok=False)
    await m.mark("wamid.X", ok=True)  # not ours: ignored
    reactions = [c for c in session.calls if isinstance(c, SetMessageReaction)]
    assert [(r.message_id, r.reaction[0].emoji) for r in reactions] == [(5, "👍"), (6, "👎")]


async def test_tg_offer_and_closed_edit_in_place(tg):
    m, session = tg
    ref = await m.offer_job(OFFER)
    send = session.calls[-1]
    assert send.text.startswith("<b>2.1 miles, £4.50, @12:30</b>\nPickup time - <b>12:30</b>")
    datas = [b.callback_data for row in send.reply_markup.inline_keyboard for b in row]
    assert datas == ["ro1:84217:a", "ro1:84217:d"]
    assert all(fits_callback_limit(RiderOffer.unpack(d)) for d in datas)
    sends_before = len(session.sends)
    await m.offer_closed(ref, "ELAS-CEKT-22", "taken")
    edit = session.calls[-1]
    assert isinstance(edit, EditMessageText) and edit.message_id == parse_tg_ref(ref)[1]
    assert edit.text == "❌ Taken by another rider · <b>ELAS-CEKT-22</b>" and edit.reply_markup is None
    assert len(session.sends) == sends_before  # no new message (D49)


async def test_tg_offer_closed_without_a_telegram_ref_does_nothing(tg):
    m, session = tg
    await m.offer_closed("wamid.X", "ELAS-1", "taken")
    assert session.calls == []


# ---- formatting ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("wa_text, html", [
    ("*bold* and _it_ and ~gone~", "<b>bold</b> and <i>it</i> and <s>gone</s>"),
    ("2*3*4 stays", "2*3*4 stays"),
    ("snake_case_name stays", "snake_case_name stays"),
    ("* not bold *", "* not bold *"),
    ("a < b & c > d", "a &lt; b &amp; c &gt; d"),
    ("```code *x*```", "<pre>code *x*</pre>"),
    ("", ""),
])
def test_wa_to_html(wa_text, html):
    assert wa_to_html(wa_text) == html


def test_long_text_is_cut_to_telegram_limit():
    out = wa_to_html("&" * 5000)
    assert len(out) <= TELEGRAM_TEXT_LIMIT and out.endswith("…") and not out[:-1].endswith("&am")


# ---- channel choice ------------------------------------------------------------------------------------------------
def test_messenger_for_picks_by_channel(recording_bot):
    bot, _ = recording_bot
    wa = MagicMock()
    assert isinstance(messenger_for(PHONE, "whatsapp", None, wa_client=wa, tg_bot=bot), WhatsAppRiderMessenger)
    tgm = messenger_for(PHONE, "telegram", 111, wa_client=wa, tg_bot=bot)
    assert isinstance(tgm, TelegramRiderMessenger) and tgm.tcid == 111
    assert isinstance(tgm, RiderMessenger)


def test_telegram_without_tcid_falls_back_to_whatsapp(recording_bot):
    bot, _ = recording_bot
    m = messenger_for(PHONE, "telegram", None, wa_client=MagicMock(), tg_bot=bot)
    assert isinstance(m, WhatsAppRiderMessenger) and m.phone == PHONE


def test_telegram_without_a_configured_bot_falls_back_to_whatsapp(monkeypatch):
    import config

    monkeypatch.setattr(config, "rider_bot", None)
    m = messenger_for(PHONE, "telegram", 111, wa_client=MagicMock())
    assert isinstance(m, WhatsAppRiderMessenger)


async def test_for_rider_reads_rider_master(monkeypatch, recording_bot):
    from ordelo.rider_messaging import factory

    bot, _ = recording_bot
    query = MagicMock()
    query.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"channel": "telegram", "tcid": 111}])
    client = MagicMock()
    client.table.return_value = query
    monkeypatch.setattr("config.client_ordelo", client)
    monkeypatch.setattr("config.rider_bot", bot)
    m = await factory.for_rider(PHONE)
    assert isinstance(m, TelegramRiderMessenger) and m.tcid == 111
    client.table.assert_called_with("rider_master")
    query.select.return_value.eq.assert_called_with("rider_id", PHONE)


async def test_use_messenger_overrides_everything():
    from ordelo.rider_messaging import for_rider

    fake = RecordingRiderMessenger()
    with use_messenger(fake):
        m = await for_rider(PHONE)
        await m.say("hello")
    assert m is fake and fake.texts == ["hello"]
    assert isinstance(messenger_for(PHONE, "whatsapp", None, wa_client=MagicMock()), WhatsAppRiderMessenger)
