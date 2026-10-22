"""Kitchen receipts driven through a real Dispatcher offline: callback update -> inbox -> OrderAction handler ->
Receipts.tap -> restaurant_actions (FakeActionsDb: the shared Ready / +N rule) -> FakeReceiptStore -> answer + redrawn copies.

Both channels act on ONE order state (FakeActionsDb), so the WhatsApp-vs-Telegram race is real here."""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.rest_admin.order_cards import OrderCards
from channels.telegram.rest_admin.order_cards.model import OrderRef
from channels.telegram.rest_admin.receipts import Receipts
from config.tgram_setting import TgramBotSettings
from utils_common.order_management import restaurant_actions
from utils_common.order_management.restaurant_actions import WhatsAppActor

from .conftest import callback_update
from .fake_receipt_store import ADA, BOB, FakeReceiptStore

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin", {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"}
)
ORDER = "ELAS-CEKT-22"
DELIVERY = OrderRef(ORDER, "delivery")
TAKEAWAY = OrderRef("ELAS-TK-1", "takeaway")
ADA_PHONE, BOB_PHONE = "447700900001", "447700900002"


@pytest.fixture
def nudges(monkeypatch):
    """Rider nudges and customer events recorded instead of run (their wording is proven in test_restaurant_actions.py)."""
    sent = []

    async def rider(rider_id, rest_name, dispatch_id=None):  # dispatch_id: that job's thread (R2)
        sent.append(("rider", rider_id, rest_name))

    async def customer(order_number, data, phone):
        sent.append(("customer", order_number, phone))

    monkeypatch.setattr(restaurant_actions, "_nudge_rider", rider)
    monkeypatch.setattr(restaurant_actions, "_announce_takeaway_ready", customer)
    return sent


@pytest.fixture
def env(recording_bot, actions_db, card_store, nudges):
    bot, session = recording_bot
    actions_db.add(ORDER, "delivery", rider="RIDER01", dispatch_id=10, pickup="2026-10-15T12:00:00+00:00")
    actions_db.add("ELAS-TK-1", "takeaway", rider=None, pickup="2026-10-15T12:00:00+00:00")
    actions_db.telegram_admins = {("rest_admin", 111): ADA_PHONE, ("rest_admin", 222): BOB_PHONE}
    actions_db.labels = {ADA_PHONE: "Ada", BOB_PHONE: "Bob"}
    store = FakeReceiptStore(actions_db)
    receipts = Receipts(bot, "rest_admin", store=store)
    cards = OrderCards(bot, "rest_admin", store=card_store)
    dp = build_rest_admin_dispatcher(SETTINGS, cards, receipts)
    uid = {"n": 100}

    async def tap(data, user_id=111, **kw):
        uid["n"] += 1
        await dp.feed_update(bot, Update.model_validate(callback_update(data, user_id, update_id=uid["n"], **kw), context={"bot": bot}))

    async def replay(data, user_id, update_id):
        await dp.feed_update(bot, Update.model_validate(callback_update(data, user_id, update_id=update_id), context={"bot": bot}))

    return receipts, store, session, actions_db, tap, replay


def edits_for(session, chat):
    return [e for e in session.edits if e.chat_id == chat]


# ---- sending -----------------------------------------------------------------------------------------------------


async def test_send_posts_a_receipt_to_every_destination_as_a_reply_to_the_card(env):
    receipts, store, session, db, tap, _ = env
    store.destinations = [type(ADA)(111, 111, ADA_PHONE, "Ada", reply_to=77), type(BOB)(222, 222, BOB_PHONE, "Bob", reply_to=None)]
    await receipts.send(DELIVERY, 10)
    assert sorted(s.chat_id for s in session.sends) == [111, 222]
    by_chat = {s.chat_id: s for s in session.sends}
    assert by_chat[111].reply_parameters.message_id == 77 and by_chat[111].reply_parameters.allow_sending_without_reply
    assert by_chat[222].reply_parameters is None
    assert by_chat[111].text.startswith("🧾 KITCHEN RECEIPT · 🚚 Delivery")
    assert len(store.live()) == 2 and all(r["status"] == "open@13:00" for r in store.live())


async def test_a_new_riders_receipt_replaces_the_old_one_in_each_chat(env):
    receipts, store, session, db, *_ = env
    await receipts.send(DELIVERY, 10)
    first = {r["tcid"]: r["message_id"] for r in store.live()}
    db.orders[("delivery", ORDER)]["inflight"] = dict(dispatch_id=11, rider_id="RIDER02", status="assigned")  # re-dispatched
    await receipts.send(DELIVERY, 11)
    assert sorted(session.deleted) == sorted((tcid, mid) for tcid, mid in first.items())
    assert len(store.live()) == 2 and all(r["dispatch_id"] == 11 for r in store.live())


async def test_send_for_a_vanished_order_sends_nothing(env):
    receipts, store, session, db, *_ = env
    del db.orders[("delivery", ORDER)]
    await receipts.send(DELIVERY, 10)
    assert session.sends == []


async def test_one_chat_failing_does_not_stop_the_other(env):
    from aiogram.exceptions import TelegramForbiddenError

    receipts, store, session, *_ = env
    session.fail = lambda m: TelegramForbiddenError(m, "blocked") if getattr(m, "chat_id", None) == 111 else None
    await receipts.send(DELIVERY, 10)
    assert [r["tcid"] for r in store.live()] == [222]


async def test_status_change_while_sending_triggers_a_redraw(env):
    receipts, store, session, db, *_ = env
    real = store.receipt_sent

    async def sent_then_ready(*a, **kw):
        out = await real(*a, **kw)
        db.orders[("delivery", ORDER)].update(ready_dispatch_id=10)  # someone tapped Ready on WhatsApp mid-send
        return out

    store.receipt_sent = sent_then_ready
    await receipts.send(DELIVERY, 10)
    assert edits_for(session, 111) and "Marked ready" in edits_for(session, 111)[-1].text


# ---- taps --------------------------------------------------------------------------------------------------------


async def test_ready_tap_notifies_the_rider_answers_and_redraws_every_copy(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    assert session.answers == [("Marked ready — rider told", False)]
    assert nudges == [("rider", "RIDER01", "Elai")]
    ada, bob = edits_for(session, 111)[-1], edits_for(session, 222)[-1]
    assert "✅ Marked ready by You" in ada.text and "✅ Marked ready by Ada" in bob.text
    assert [b.callback_data.split(":")[3] for b in ada.reply_markup.inline_keyboard[0]] == ["adj", "adj"]
    assert {r["status"] for r in store.live()} == {"ready@13:00"}


async def test_second_ready_tap_by_the_other_admin_is_told_and_does_not_nudge_again(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    await tap(f"ord:{ORDER}:d:rdy:0", 222)
    assert session.answers[-1] == ("Already marked ready by Ada", False)
    assert len(nudges) == 1


async def test_plus_ten_moves_the_pickup_and_is_not_cumulative(env):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:adj:10", 111)
    assert session.answers[-1] == ("Pickup 1:10 PM", False)
    assert db.orders[("delivery", ORDER)]["pickup"] == "2026-10-15T12:10:00+00:00"
    await tap(f"ord:{ORDER}:d:adj:10", 111)                                   # same button again: nothing changes
    assert session.answers[-1] == ("Pickup already 1:10 PM", False)
    await tap(f"ord:{ORDER}:d:adj:20", 222)                                   # +20 is over the ORIGINAL pickup, not +30
    assert db.orders[("delivery", ORDER)]["pickup"] == "2026-10-15T12:20:00+00:00"
    last = edits_for(session, 111)[-1].text
    assert "⏰ Pickup: <b>1:20 PM</b> (moved +20 by Bob)" in last and "(+10)" not in last.split("Items")[0]
    assert {r["status"] for r in store.live()} == {"open@13:20"}


async def test_non_admin_tap_is_refused_and_changes_nothing(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    before = len(session.edits)
    await tap(f"ord:{ORDER}:d:rdy:0", 999)
    assert session.answers == [("You're not an admin for this restaurant any more.", True)]
    assert db.orders[("delivery", ORDER)]["ready_at"] is None and nudges == [] and len(session.edits) == before


async def test_revoked_admin_copy_turns_into_the_locked_view_on_refresh(env):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    store.destinations = [BOB]            # Ada's invite revoked
    db.telegram_admins.pop(("rest_admin", 111))
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    assert session.answers[-1][1] is True
    ada = edits_for(session, 111)
    assert ada and ada[-1].text.startswith("🔒") and ada[-1].reply_markup is None
    assert db.orders[("delivery", ORDER)]["ready_at"] is None


async def test_stale_ready_button_after_pickup_is_refused_and_copies_show_picked_up(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    db.orders[("delivery", ORDER)]["inflight"]["status"] = "pickedup"
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    assert session.answers == [("Food already picked up", False)] and nudges == []
    last = edits_for(session, 111)[-1]
    assert "🛵 Picked up by the rider" in last.text and last.reply_markup is None


async def test_tap_on_a_cancelled_riders_receipt(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    db.orders[("delivery", ORDER)]["inflight"] = None                         # rider cancelled, nobody new yet
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    assert session.answers == [("This order is no longer in progress", False)] and nudges == []
    assert "⚠️ This rider is no longer on the job" in edits_for(session, 111)[-1].text
    assert [r["state"] for r in store.ledger] == ["closed", "closed"]


async def test_repeated_update_is_handled_once(env, nudges):
    receipts, store, session, db, tap, replay = env
    await receipts.send(DELIVERY, 10)
    await replay(f"ord:{ORDER}:d:rdy:0", 111, 555)
    await replay(f"ord:{ORDER}:d:rdy:0", 111, 555)                            # Telegram re-delivers the same update
    assert [c[0] for c in db.calls].count("t_order_ready") == 1 and len(nudges) == 1


async def test_whatsapp_ready_first_then_telegram_tap_loses_and_copies_catch_up(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    won = await restaurant_actions.ready(ORDER, "delivery", WhatsAppActor(ADA_PHONE))
    assert won.result == "ok"
    await tap(f"ord:{ORDER}:d:rdy:0", 222)
    assert session.answers == [("Already marked ready by Ada", False)]
    assert len(nudges) == 1
    assert "✅ Marked ready by Ada" in edits_for(session, 222)[-1].text


async def test_whatsapp_tap_alone_is_caught_by_the_sweep_refresh(env):
    receipts, store, session, db, *_ = env
    await receipts.send(DELIVERY, 10)
    await restaurant_actions.adjust_pickup(ORDER, WhatsAppActor(ADA_PHONE), target="2026-10-15T12:10:00+00:00")
    await receipts.refresh(DELIVERY)                                          # what POST /order-alerts {"receipts": [...]} runs
    assert len(session.edits) == 2 and all("(moved +10 by" in e.text for e in session.edits)
    session.calls.clear()
    await receipts.refresh(DELIVERY)                                          # nothing stale any more: silent
    assert session.calls == []


async def test_downstream_failure_still_records_ready_and_tells_the_admin(env, monkeypatch):
    receipts, store, session, db, tap, _ = env

    async def boom(rider_id, rest_name):
        raise RuntimeError("rider agent down")

    monkeypatch.setattr(restaurant_actions, "_nudge_rider", boom)
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    text, alert = session.answers[-1]
    assert alert is True and "could not be messaged" in text
    assert db.orders[("delivery", ORDER)]["ready_at"] is not None
    assert "✅ Marked ready" in edits_for(session, 111)[-1].text


async def test_database_failure_answers_with_the_trouble_text_and_changes_nothing(env):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    db.fail_with = RuntimeError("db down")
    await tap(f"ord:{ORDER}:d:rdy:0", 111)
    assert session.answers == [("Sorry, something went wrong on our side. Please try again in a minute.", True)]
    assert session.edits == []


async def test_group_shaped_update_acts_as_the_user_not_the_chat(env):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:rdy:0", 111, chat_id=-1001234)
    call = [c for c in db.calls if c[0] == "t_order_ready"][0]
    assert call[1]["p_tuid"] == 111 and "p_tcid" not in call[1]
    assert db.orders[("delivery", ORDER)]["ready_by"] == ADA_PHONE


async def test_forged_adjust_minutes_are_refused_without_touching_the_order(env):
    receipts, store, session, db, tap, _ = env
    await receipts.send(DELIVERY, 10)
    await tap(f"ord:{ORDER}:d:adj:15", 111)
    assert session.answers[-1][1] is True and db.orders[("delivery", ORDER)]["pickup"] == "2026-10-15T12:00:00+00:00"


# ---- takeaway ----------------------------------------------------------------------------------------------------


async def test_takeaway_receipt_ready_tap_notifies_the_customer(env, nudges):
    receipts, store, session, db, tap, _ = env
    await receipts.send(TAKEAWAY, None)
    sent = [s for s in session.sends if s.chat_id == 111][0]
    assert "🥡 Takeaway" in sent.text and [b.callback_data for b in sent.reply_markup.inline_keyboard[0]] == ["ord:ELAS-TK-1:t:rdy:0"]
    await tap("ord:ELAS-TK-1:t:rdy:0", 111)
    assert session.answers == [("Marked ready — customer told", False)] and nudges == [("customer", "ELAS-TK-1", ADA_PHONE)]
    last = edits_for(session, 111)[-1]
    assert "✅ Marked ready by You" in last.text and last.reply_markup is None


async def test_old_card_buttons_still_reach_the_order_cards(env, card_store):
    receipts, store, session, db, tap, _ = env
    order = card_store.add_order(destinations=[ADA])
    card_store.admins = {111: type("A", (), {"label": "Ada", "phone": ADA_PHONE})()}
    await tap(f"ord:{order.order_number}:d:acc:0", 111)
    assert session.answers == [("Accepted — pick a time", False)] and "t_order_ready" not in [c[0] for c in db.calls]


# ---- sequences between the pieces ----------------------------------------------------------------------------------


async def test_a_failed_snapshot_during_refresh_leaves_the_copies_claimed_not_closed_or_replaced(env):
    receipts, store, session, db, *_ = env
    await receipts.send(DELIVERY, 10)
    db.orders[("delivery", ORDER)]["pickup"] = "2026-10-15T12:10:00+00:00"   # the copies are now stale, so refresh claims them
    store.fail_snapshot = True
    before = (len(session.edits), len(session.deleted))
    await receipts.refresh(DELIVERY)
    assert (len(session.edits), len(session.deleted)) == before              # no "no longer available" replacement
    assert {r["state"] for r in store.ledger} == {"taken"}                    # still claimed: the 30 s re-offer retries them
    assert not any(r["state"] == "closed" for r in store.ledger)


async def test_a_delayed_event_for_the_old_rider_does_not_touch_the_current_receipts(env):
    receipts, store, session, db, *_ = env
    db.orders[("delivery", ORDER)]["inflight"] = dict(dispatch_id=11, rider_id="RIDER02", status="assigned")
    await receipts.send(DELIVERY, 11)
    current = {r["tcid"]: r["message_id"] for r in store.live()}
    sends, deletes = len(session.sends), len(session.deleted)
    await receipts.send(DELIVERY, 10)                                          # the old rider's event arrives late
    assert (len(session.sends), len(session.deleted)) == (sends, deletes)
    assert {r["tcid"]: r["message_id"] for r in store.live()} == current


async def test_cancel_then_refresh_then_reassign_deletes_the_cancelled_receipt(env):
    receipts, store, session, db, *_ = env
    await receipts.send(DELIVERY, 10)
    old = sorted((r["tcid"], r["message_id"]) for r in store.live())
    db.orders[("delivery", ORDER)]["inflight"] = None                          # rider cancelled
    await receipts.refresh(DELIVERY)                                           # copies edited to "no longer on the job", ledger closed
    assert store.live() == [] and session.deleted == []
    db.orders[("delivery", ORDER)]["inflight"] = dict(dispatch_id=11, rider_id="RIDER02", status="assigned")
    await receipts.send(DELIVERY, 11)                                          # D35: the new rider's receipt replaces the old ones
    assert sorted(session.deleted) == old
    assert len(store.live()) == 2 and all(r["dispatch_id"] == 11 for r in store.live())
