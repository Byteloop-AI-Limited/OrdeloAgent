"""OrderCards.remind / refresh against FakeCardStore (SQL contract fake) and RecordingSession (no network)."""

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import DeleteMessage, EditMessageText

from channels.telegram.rest_admin.order_cards import OrderCards
from channels.telegram.rest_admin.order_cards import io as io_mod
from channels.telegram.rest_admin.order_cards.model import Actor, Destination

ADA, BOB = "447700900001", "447700900002"
ADA_D, BOB_D = Destination(111, 111, ADA, "Ada"), Destination(222, 222, BOB, "Bob")
GROUP_D = Destination(-100, None, None, None)
M = DeleteMessage(chat_id=1, message_id=1)


def bad(msg):
    return TelegramBadRequest(method=M, message=msg)


@pytest.fixture
def cards(recording_bot, card_store):
    bot, session = recording_bot
    return OrderCards(bot, "rest_admin", store=card_store), card_store, session


async def test_remind_sends_one_copy_per_destination_and_records_them(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    await oc.remind(order, 1, 4)
    assert sorted(c.chat_id for c in session.sends) == [111, 222]
    assert all(c.text.startswith("🔔 New order — accept or decline\n") for c in session.sends)
    assert "reminder" not in session.sends[0].text
    assert [(r["tcid"], r["state"], r["card_status"]) for r in store.ledger] == [(111, "live", "awaiting"), (222, "live", "awaiting")]
    kb = session.sends[0].reply_markup.inline_keyboard[0]
    assert [b.callback_data for b in kb] == ["ord:ELAS-CEKT-22:d:acc:0", "ord:ELAS-CEKT-22:d:dec:0"]
    assert session.sends[0].parse_mode == "HTML"


async def test_repeat_reminder_replaces_previous_copy_in_each_chat(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    await oc.remind(order, 1, 4)
    first_ids = {r["tcid"]: r["message_id"] for r in store.ledger}
    await oc.remind(order, 2, 4)
    assert "· reminder 2 of 4" in session.sends[-1].text
    assert sorted(session.deleted) == sorted(first_ids.items())
    assert [(r["state"], r["close_reason"]) for r in store.ledger[:2]] == [("closed", "deleted")] * 2
    assert [r["state"] for r in store.ledger[2:]] == ["live", "live"]


async def test_remind_sends_nothing_for_a_decided_order_and_updates_old_copies_instead(cards):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    store.set_status(order.order_number, "accepted", Actor("Ada", ADA))
    n_sends = len(session.sends)
    await oc.remind(order, 2, 4)
    assert len(session.sends) == n_sends  # nothing new
    assert session.edits[-1].text.startswith("✅ You accepted — choose a pickup time")
    assert session.edits[-1].chat_id == 111 and store.ledger[0]["card_status"] == "accepted"


async def test_remind_unknown_order_is_quiet(cards):
    oc, store, session = cards
    from channels.telegram.rest_admin.order_cards import OrderRef

    await oc.remind(OrderRef("NOPE-1", "delivery"), 1, 4)
    assert session.calls == []


async def test_order_decided_while_sending_is_refreshed_afterwards(cards):
    oc, store, session = cards
    order = store.add_order()
    store.on_card_sent = lambda s, o, d: s.set_status(o.order_number, "declined", Actor("Bob", BOB))
    await oc.remind(order, 1, 4)
    assert len(session.sends) == 1
    assert session.edits[-1].text.startswith("❌ Declined by Bob")
    assert store.ledger[0]["state"] == "closed"


async def test_blocked_admin_does_not_stop_the_others(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    session.fail = lambda m: TelegramForbiddenError(method=M, message="Forbidden: bot was blocked by the user") \
        if getattr(m, "chat_id", None) == 111 else None
    await oc.remind(order, 1, 4)
    assert [r["tcid"] for r in store.ledger] == [222]


async def test_group_destination_gets_third_person_text(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[GROUP_D])
    await oc.remind(order, 1, 4)
    assert store.ledger[0]["tuid"] is None
    store.set_status(order.order_number, "accepted", Actor("Ada", ADA))
    await oc.refresh(order)
    assert session.edits[-1].text.startswith("✅ Accepted by Ada")
    assert len(session.edits[-1].reply_markup.inline_keyboard[0]) == 3  # any authorised tapper may pick the time


async def test_refresh_edits_each_copy_to_its_viewers_view(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    await oc.remind(order, 1, 4)
    store.set_status(order.order_number, "accepted", Actor("Ada", ADA))
    await oc.refresh(order)
    by_chat = {e.chat_id: e for e in session.edits}
    assert by_chat[111].text.startswith("✅ You accepted — choose a pickup time") and by_chat[111].reply_markup
    assert by_chat[222].text.startswith("✅ Accepted by Ada — waiting for pickup time") and by_chat[222].reply_markup is None
    assert [r["state"] for r in store.ledger] == ["live", "live"]  # accepted is not final


async def test_refresh_closes_terminal_copies_and_is_idempotent(cards):
    from datetime import datetime, timezone

    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D])
    await oc.remind(order, 1, 4)
    store.set_status(order.order_number, "pickup_set", Actor("Ada", ADA), datetime(2026, 1, 15, 12, 15, tzinfo=timezone.utc))
    await oc.refresh(order)
    assert session.edits[-1].text.startswith("✅ You accepted · pickup 12:15 PM")
    assert store.ledger[0]["state"] == "closed" and store.ledger[0]["close_reason"] == "edited"
    n = len(session.calls)
    await oc.refresh(order)
    assert len(session.calls) == n  # nothing left to do, no Telegram traffic


async def test_refresh_leaves_up_to_date_copies_alone(cards):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    n = len(session.calls)
    await oc.refresh(order)
    assert len(session.calls) == n


async def test_revoked_viewer_gets_the_locked_view(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    await oc.remind(order, 1, 4)
    store.orders[order.order_number]["destinations"] = (BOB_D,)  # Ada's invite revoked
    await oc.refresh(order)
    assert [(e.chat_id, e.text.startswith("🔒")) for e in session.edits] == [(111, True)]
    assert session.edits[0].reply_markup is None
    assert [r["state"] for r in store.ledger] == ["closed", "live"]


async def test_vanished_order_edits_copies_to_no_longer_available(cards):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    del store.orders[order.order_number]
    await oc.refresh(order)
    assert session.edits[-1].text == "This order is no longer available."
    assert store.ledger[0]["state"] == "closed"


@pytest.mark.parametrize(
    "error,state,reason",
    [
        (bad("Bad Request: message is not modified: specified new message content and reply markup are exactly the same"), "closed", "edited"),
        (bad("Bad Request: message to edit not found"), "closed", "gone"),
        (bad("Bad Request: message can't be edited"), "closed", "gone"),
        (bad("Bad Request: chat not found"), "closed", "gone"),
        (TelegramForbiddenError(method=M, message="Forbidden: bot was blocked by the user"), "closed", "gone"),
        (bad("Bad Request: something unexpected"), "taken", None),
        (TelegramNetworkError(method=M, message="boom"), "taken", None),
    ],
)
async def test_edit_error_mapping(cards, error, state, reason):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    store.set_status(order.order_number, "declined", Actor("Ada", ADA))
    session.fail = lambda m: error if isinstance(m, EditMessageText) else None
    await oc.refresh(order)
    assert (store.ledger[0]["state"], store.ledger[0]["close_reason"]) == (state, reason)


async def test_retry_after_sleeps_once_then_succeeds(cards, monkeypatch):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    store.set_status(order.order_number, "declined", Actor("Ada", ADA))
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(io_mod.asyncio, "sleep", fake_sleep)
    attempts = {"n": 0}

    def fail(m):
        if isinstance(m, EditMessageText):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return TelegramRetryAfter(method=M, message="Too Many Requests", retry_after=7)

    session.fail = fail
    await oc.refresh(order)
    assert slept == [7] and attempts["n"] == 2 and store.ledger[0]["state"] == "closed"


async def test_failed_delete_stays_claimed_until_reoffered(cards):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    session.fail = lambda m: bad("Bad Request: something unexpected") if isinstance(m, DeleteMessage) else None
    await oc.remind(order, 2, 4)
    old = store.ledger[0]
    assert old["state"] == "taken" and old["taken_for"] == "delete" and store.ledger[1]["state"] == "live"
    # the sweep re-offers it later: the delete is retried (and now works)
    session.fail = None
    old["reoffer"] = True
    await oc.refresh(order)
    assert old["state"] == "closed" and old["close_reason"] == "deleted"


async def test_deleted_by_user_counts_as_gone(cards):
    oc, store, session = cards
    order = store.add_order()
    await oc.remind(order, 1, 4)
    session.fail = lambda m: bad("Bad Request: message to delete not found") if isinstance(m, DeleteMessage) else None
    await oc.remind(order, 2, 4)
    assert (store.ledger[0]["state"], store.ledger[0]["close_reason"]) == ("closed", "gone")


async def test_store_error_in_one_destination_is_logged_not_raised(cards):
    oc, store, session = cards
    order = store.add_order(destinations=[ADA_D, BOB_D])
    real = store.card_sent
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")
        return await real(*a, **k)

    store.card_sent = flaky
    await oc.remind(order, 1, 4)
    assert len(session.sends) == 2 and len(store.ledger) == 1
