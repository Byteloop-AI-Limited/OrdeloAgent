"""Order-card taps driven through a real Dispatcher offline: callback update -> inbox -> OrderAction handler ->
OrderCards.tap -> FakeCardStore (mimics t_order_decide / t_order_set_pickup) -> answer + refreshed copies."""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.rest_admin.order_cards import OrderCards
from channels.telegram.rest_admin.order_cards.model import Destination
from config.tgram_setting import TgramBotSettings

from .conftest import callback_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin", {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"}
)
ADA_D = Destination(111, 111, "447700900001", "Ada")
BOB_D = Destination(222, 222, "447700900002", "Bob")
ORDER = "ELAS-CEKT-22"


@pytest.fixture
def env(recording_bot, card_store):
    bot, session = recording_bot
    cards = OrderCards(bot, "rest_admin", store=card_store)
    dp = build_rest_admin_dispatcher(SETTINGS, cards)
    uid = {"n": 100}

    async def tap(data, user_id=111, **kw):
        uid["n"] += 1
        await dp.feed_update(bot, Update.model_validate(callback_update(data, user_id, update_id=uid["n"], **kw), context={"bot": bot}))

    return cards, card_store, session, tap


async def two_admins(cards, store):
    order = store.add_order(destinations=[ADA_D, BOB_D])
    await cards.remind(order, 1, 4)
    return order


def edits_for(session, chat):
    return [e for e in session.edits if e.chat_id == chat]


async def test_accept_shows_pickup_buttons_to_tapper_and_name_to_the_other_admin(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    assert session.answers == [("Accepted — pick a time", False)]
    ada, bob = edits_for(session, 111)[-1], edits_for(session, 222)[-1]
    assert ada.text.startswith("✅ You accepted — choose a pickup time")
    assert [b.callback_data for b in ada.reply_markup.inline_keyboard[0]] == [f"ord:{ORDER}:d:pk:{m}" for m in (5, 15, 25)]
    assert bob.text.startswith("✅ Accepted by Ada — waiting for pickup time") and bob.reply_markup is None


async def test_second_admin_accept_is_told_who_decided(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    await tap(f"ord:{ORDER}:d:acc:0", 222)
    assert session.answers[-1] == ("Already accepted by Ada", False)
    assert store.orders[ORDER]["decided_by"].label == "Ada"
    assert edits_for(session, 222)[-1].text.startswith("✅ Accepted by Ada")


async def test_decline(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:dec:0", 222)
    assert session.answers == [("Declined", False)]
    assert edits_for(session, 222)[-1].text.startswith("❌ You declined this order")
    assert edits_for(session, 111)[-1].text.startswith("❌ Declined by Bob")
    assert [r["state"] for r in store.ledger] == ["closed", "closed"]


async def test_non_admin_tap_is_refused_and_changes_nothing(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:acc:0", 999)
    assert session.answers == [("You're not an admin for this restaurant any more.", True)]
    assert store.orders[ORDER]["status"] == "awaiting" and session.edits == []


async def test_revoked_admin_tap_turns_their_card_into_the_locked_view(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    store.admins.pop(111)  # Ada's invite revoked
    store.orders[ORDER]["destinations"] = (BOB_D,)
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    assert session.answers[-1][1] is True
    assert [(e.chat_id, e.text.startswith("🔒")) for e in session.edits] == [(111, True)]
    assert store.orders[ORDER]["status"] == "awaiting"


async def test_pickup_closes_both_copies_with_the_time(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    await tap(f"ord:{ORDER}:d:pk:15", 111)
    assert session.answers[-1] == ("Pickup 12:15 PM", False)
    assert edits_for(session, 111)[-1].text.startswith("✅ You accepted · pickup 12:15 PM")
    assert edits_for(session, 222)[-1].text.startswith("✅ Accepted by Ada · pickup 12:15 PM")
    assert [r["state"] for r in store.ledger] == ["closed", "closed"]


async def test_pickup_by_another_admin_after_it_is_set(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    await tap(f"ord:{ORDER}:d:pk:5", 111)
    await tap(f"ord:{ORDER}:d:pk:25", 222)
    assert session.answers[-1] == ("Pickup already set to 12:05 PM", False)


async def test_pickup_before_accept_is_refused(env):
    cards, store, session, tap = env
    await two_admins(cards, store)
    await tap(f"ord:{ORDER}:d:pk:15", 111)
    assert session.answers == [("This order is not accepted yet.", False)]


async def test_tap_on_vanished_order(env):
    cards, store, session, tap = env
    order = await two_admins(cards, store)
    del store.orders[order.order_number]
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    assert session.answers == [("This order is no longer available.", False)]
    assert all(e.text == "This order is no longer available." for e in session.edits)


async def test_takeaway_tap_uses_takeaway_type(env):
    cards, store, session, tap = env
    order = store.add_order("ELAS-TK-1", "takeaway", destinations=[ADA_D])
    await cards.remind(order, 1, 4)
    assert "ord:ELAS-TK-1:t:acc:0" in [b.callback_data for b in session.sends[0].reply_markup.inline_keyboard[0]]
    await tap("ord:ELAS-TK-1:t:dec:0", 111)
    assert store.orders["ELAS-TK-1"]["status"] == "declined"


async def test_group_tap_is_authorised_by_user_not_chat(env):
    """D27: the card lives in a group chat (id -100); the tapper is user 111; the chat id is never an actor."""
    cards, store, session, tap = env
    group = Destination(-100, None, None, None)
    order = store.add_order(destinations=[group])
    await cards.remind(order, 1, 4)
    await tap(f"ord:{ORDER}:d:acc:0", 111, chat_id=-100, message_id=session.next_message_id)
    assert session.answers == [("Accepted — pick a time", False)]
    assert store.orders[ORDER]["decided_by"].label == "Ada"
    assert edits_for(session, -100)[-1].text.startswith("✅ Accepted by Ada")  # third person in a shared chat
    await tap(f"ord:{ORDER}:d:pk:5", 222, chat_id=-100)  # another authorised user picks the time
    assert edits_for(session, -100)[-1].text.startswith("✅ Accepted by Bob · pickup 12:05 PM")  # last writer is recorded
    await tap(f"ord:{ORDER}:d:acc:0", -100)  # a chat id is not a user
    assert session.answers[-1][1] is True


async def test_unexpected_error_answers_with_trouble_and_does_not_raise(env):
    cards, store, session, tap = env
    await two_admins(cards, store)

    async def boom(*a, **k):
        raise RuntimeError("db down")

    store.decide = boom
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    from channels.telegram.rest_admin.router import TROUBLE

    assert session.answers == [(TROUBLE, True)]
    assert store.orders[ORDER]["status"] == "awaiting"


async def test_expired_callback_query_still_refreshes(env):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import AnswerCallbackQuery

    cards, store, session, tap = env
    await two_admins(cards, store)
    session.fail = lambda m: TelegramBadRequest(method=m, message="Bad Request: query is too old") \
        if isinstance(m, AnswerCallbackQuery) else None
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    assert store.orders[ORDER]["status"] == "accepted"
    assert edits_for(session, 222)[-1].text.startswith("✅ Accepted by Ada")


async def test_same_callback_delivered_twice_is_handled_once(env, inbox_db):
    cards, store, session, tap = env
    await two_admins(cards, store)
    bot = cards._io._bot
    dp = build_rest_admin_dispatcher(SETTINGS, cards)
    upd = Update.model_validate(callback_update(f"ord:{ORDER}:d:acc:0", 111, update_id=555), context={"bot": bot})
    await dp.feed_update(bot, upd)
    await dp.feed_update(bot, upd)
    assert [c for c in store.calls if c.startswith("decide")] == ["decide:accept"]
    assert len(session.answers) == 1


async def test_text_message_is_not_taken_by_the_orders_router(env):
    from .conftest import message_update

    cards, store, session, tap = env
    bot = cards._io._bot
    dp = build_rest_admin_dispatcher(SETTINGS, cards)
    await dp.feed_update(bot, Update.model_validate(message_update("hello"), context={"bot": bot}))
    assert "Try /help" in session.sent_texts[0]


async def test_hanging_answer_does_not_block_the_redraw(env, monkeypatch):
    """A Bot API call that hangs (dead pooled connection) must cost at most ANSWER_TIMEOUT_SECS, not the handler limit."""
    import asyncio

    from aiogram.methods import AnswerCallbackQuery

    from channels.telegram import replies

    monkeypatch.setattr(replies, "CALLBACK_ANSWER_TIMEOUT_SECS", 0.05)
    cards, store, session, tap = env
    await two_admins(cards, store)
    real = session.make_request

    async def make_request(bot, method, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            await asyncio.sleep(30)
        return await real(bot, method, timeout)

    session.make_request = make_request
    await asyncio.wait_for(tap(f"ord:{ORDER}:d:acc:0", 111), timeout=5)
    assert store.orders[ORDER]["status"] == "accepted"
    assert edits_for(session, 111)[-1].text.startswith("✅ You accepted")
    assert edits_for(session, 222)[-1].text.startswith("✅ Accepted by Ada")


async def test_toast_and_redraw_run_together(env, monkeypatch):
    """A slow answer and slow edits overlap: the tap costs about one slow call, not the sum."""
    import asyncio
    import time

    from aiogram.methods import AnswerCallbackQuery, EditMessageText

    cards, store, session, tap = env
    await two_admins(cards, store)
    real = session.make_request

    async def slow(bot, method, timeout=None):
        if isinstance(method, (AnswerCallbackQuery, EditMessageText)):
            await asyncio.sleep(0.2)
        return await real(bot, method, timeout)

    session.make_request = slow
    t0 = time.monotonic()
    await tap(f"ord:{ORDER}:d:acc:0", 111)
    assert time.monotonic() - t0 < 0.5  # sequential would be >= 0.6 (answer + two edits)
    assert len(session.edits) == 2 and len(session.answers) == 1


async def test_remind_sends_to_destinations_at_once(env):
    import asyncio
    import time

    from aiogram.methods import SendMessage

    cards, store, session, tap = env
    order = store.add_order(destinations=[ADA_D, BOB_D])
    real = session.make_request

    async def slow(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            await asyncio.sleep(0.2)
        return await real(bot, method, timeout)

    session.make_request = slow
    t0 = time.monotonic()
    await cards.remind(order, 1, 4)
    assert time.monotonic() - t0 < 0.35 and len(store.ledger) == 2
