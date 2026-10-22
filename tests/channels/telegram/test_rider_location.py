"""A shared location on the rider bot (phase R5, D50), driven through a real Dispatcher offline.
channels/telegram/rider/location.py -> WaLocation.receive_current_location (faked here; the correlation rules are the
WhatsApp ones, tests/ordelo/test_wa_location.py) -> the agent acknowledges on the job's thread.

Scenario rows: the button share (correlated / nothing pending), a live location or picked place refused, not linked, the
receipt's ids are MsgRefs with source 'telegram_current', a WhatsApp job is never acknowledged on Telegram, WaLocation down.
"""

from __future__ import annotations

import pytest
from aiogram.types import Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.rider import location
from config.tgram_setting import TgramBotSettings
from ordelo.agents.rider_threads import RiderThread

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token": "654321:TEST-rider", "tgram_rider_webhook_secret": "abc"})
PHONE = "447700900521"


def location_update(*, live_period=None, venue=False, reply_to=None, user_id=111) -> dict:
    loc = {"latitude": 51.0688, "longitude": -1.7945, **({"live_period": live_period} if live_period else {})}
    msg = {
        "message_id": 42,
        "date": 1_700_000_000,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Ada"},
        "location": loc,
    }
    if venue:
        msg["venue"] = {"location": loc, "title": "Somewhere", "address": "1 High St"}
    if reply_to:
        msg["reply_to_message"] = {"message_id": reply_to, "date": 1_699_999_000, "chat": {"id": user_id, "type": "private"},
                                   "text": "Please share your current location."}
    return {"update_id": 9, "message": msg}


async def feed(bot, payload):
    await build_rider_dispatcher(SETTINGS).feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


@pytest.fixture
def world(monkeypatch, rider_db):
    """WaLocation, the rider's thread and the agent runner, faked; spawned work is run by drain()."""

    class World:
        correlated = 1
        receipts: list = []
        thread: RiderThread | None = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number="ELAS-ABCD-1",
                                                 channel="telegram", tcid=111)
        agent_runs: list[dict] = []
        fail = False
        pending: list = []

    w = World()
    w.receipts, w.agent_runs, w.pending = [], [], []

    class FakeWaLocation:
        def __init__(self, **_):
            pass

        async def receive_current_location(self, receipt):
            if w.fail:
                raise RuntimeError("db down")
            w.receipts.append(receipt)
            return w.correlated

    async def active_for_rider(rider_id, touch=True):
        return w.thread

    async def fake_run(**kwargs):
        w.agent_runs.append(kwargs)

    monkeypatch.setattr("ordelo.wa_location.WaLocation", FakeWaLocation)
    monkeypatch.setattr(location.rider_threads, "active_for_rider", active_for_rider)
    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", fake_run)
    monkeypatch.setattr(location.jobs, "spawn", lambda coro, what: w.pending.append(coro))

    async def drain():
        while w.pending:
            await w.pending.pop(0)

    w.drain = drain
    return w


async def test_a_button_share_is_stored_as_telegram_current_and_acknowledged_by_the_agent(recording_bot, rider_db, world):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    await feed(bot, location_update(reply_to=40))
    await world.drain()
    (r,) = world.receipts
    assert (r.rider_id, r.source, r.inbound_message_id, r.reply_to_message_id) == (PHONE, "telegram_current", "tg:111:42", "tg:111:40")
    assert (r.latitude, r.longitude) == (51.0688, -1.7945) and r.observed_at.tzinfo is not None
    assert world.agent_runs == [{"recipient": PHONE, "thread_id": "ORDELO-dispatch-7", "system_msg": location.ACK_SYSTEM_MSG}]
    assert session.sent_texts == []  # the acknowledgement is the agent's


async def test_an_unsolicited_share_gets_a_short_reply_and_the_keyboard_removed(recording_bot, rider_db, world):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    world.correlated = 0
    await feed(bot, location_update())
    await world.drain()
    assert world.receipts[0].reply_to_message_id is None and world.agent_runs == []
    assert session.sent_texts == [location.NOTHING_PENDING]
    assert session.sends[-1].reply_markup.remove_keyboard is True


async def test_a_whatsapp_job_is_not_acknowledged_on_telegram(recording_bot, rider_db, world):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    world.thread = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number="ELAS-ABCD-1", channel="whatsapp")
    await feed(bot, location_update())
    await world.drain()
    assert world.receipts and world.agent_runs == []


@pytest.mark.parametrize("kwargs", [{"live_period": 900}, {"venue": True}])
async def test_live_locations_and_picked_places_are_refused(recording_bot, rider_db, world, kwargs):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    await feed(bot, location_update(**kwargs))
    await world.drain()
    assert world.receipts == [] and session.sent_texts == [location.USE_THE_BUTTON]
    assert session.last_keyboard.keyboard[0][0].request_location is True


async def test_a_share_from_someone_not_linked(recording_bot, rider_db, world):
    bot, session = recording_bot
    await feed(bot, location_update())
    await world.drain()
    assert world.receipts == [] and session.sent_texts == [location.NOT_LINKED]


async def test_wa_location_down_says_try_again(recording_bot, rider_db, world):
    bot, session = recording_bot
    rider_db.add(PHONE, tuid=111, tcid=111)
    world.fail = True
    await feed(bot, location_update())
    await world.drain()
    assert session.sent_texts == [location.TROUBLE]
