"""The rider bot's job handlers (phase R4), driven through a real Dispatcher offline.

channels/telegram/rider/jobs.py: offer taps (ro1), job-card taps (rj1), /job and a rider's text.
The domain calls are faked at their seams: dispatch_channel (the offer row), dispatch_actions.respond_to_offer (the shared
offer rules, tested in tests/ordelo/test_dispatch_actions.py), rider_threads (the thread SQL, tested in
tests/sql/test_rider_threads_sql.py) and the agent runner (only the spawned coroutine is captured).
Scenario rows (telegram-vertification-loop): allowed actor, not linked, another rider's offer/job, stale/closed job,
DB down, wrong channel, callbacks within 64 bytes.
"""

from __future__ import annotations

import pytest
from aiogram.methods import EditMessageText, SendChatAction, SendMessage
from aiogram.types import Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.callbacks import RiderJobAction, RiderOffer, fits_callback_limit
from channels.telegram.keyboards import rider_job_card_kb, rider_offer_kb
from channels.telegram.rider import jobs
from config.tgram_setting import TgramBotSettings
from ordelo import dispatch_actions
from ordelo.agents.rider_threads import RiderThread
from ordelo.rider_messaging import DispatchChannel, JOB_CARD_ACTIONS

from .conftest import callback_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token": "654321:TEST-rider", "tgram_rider_webhook_secret": "abc"})
PHONE = "447700900501"
ORDER = "ELAS-ABCD-1"


async def feed(bot, payload: dict):
    dp = build_rider_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


@pytest.fixture
def linked(rider_db):
    return rider_db.add(PHONE, tuid=111, tcid=111)


@pytest.fixture
def offers(monkeypatch):
    """dispatch_channel + respond_to_offer fakes."""

    class Offers:
        rows: dict[int, DispatchChannel] = {}
        outcome = dispatch_actions.ACCEPTED
        calls: list[tuple] = []
        fail = False

    o = Offers()
    o.rows = {7: DispatchChannel(7, PHONE, "telegram", 111, "tg:111:10", ORDER, "unassigned")}
    o.calls = []

    async def fake_dc(dispatch_id):
        if o.fail:
            raise RuntimeError("db down")
        return o.rows.get(dispatch_id)

    async def fake_respond(rider_id, dispatch_id, order_number, accept):
        o.calls.append((rider_id, dispatch_id, order_number, accept))
        return dispatch_actions.OfferOutcome(o.outcome, order_number, dispatch_id)

    monkeypatch.setattr(jobs, "dispatch_channel", fake_dc)
    monkeypatch.setattr(jobs.dispatch_actions, "respond_to_offer", fake_respond)
    return o


@pytest.fixture
def threads(monkeypatch):
    class Threads:
        active: RiderThread | None = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number=ORDER,
                                                 dispatch_status="assigned", channel="telegram", tcid=111)
        by_dispatch: dict[int, RiderThread] = {}
        touched: list[bool] = []

    t = Threads()
    t.by_dispatch = {7: t.active}
    t.touched = []

    async def active_for_rider(rider_id, touch=True):
        t.touched.append(touch)
        return t.active if t.active and t.active.rider_id == rider_id else None

    async def for_dispatch(dispatch_id):
        return t.by_dispatch.get(dispatch_id)

    monkeypatch.setattr(jobs.rider_threads, "active_for_rider", active_for_rider)
    monkeypatch.setattr(jobs.rider_threads, "for_dispatch", for_dispatch)
    return t


@pytest.fixture
def spawned(monkeypatch):
    """Capture what would run in the background (the agent turn) instead of running the graph."""
    runs: list[tuple[str, tuple, dict]] = []

    async def fake_run_rider_agent(thread, **kwargs):
        runs.append(("run_rider_agent", (thread,), kwargs))

    async def fake_run_custom(recipient=None, **kwargs):
        runs.append(("run_rider_agent_w_custom_msg", (recipient,), kwargs))

    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent", fake_run_rider_agent)
    monkeypatch.setattr("ordelo.agents.agent_runner.run_rider_agent_w_custom_msg", fake_run_custom)
    pending = []
    monkeypatch.setattr(jobs, "spawn", lambda coro, what: pending.append(coro))

    async def drain():
        while pending:
            await pending.pop(0)
        return runs

    return drain


# ---- callbacks fit -------------------------------------------------------------------------------------------------
def test_offer_and_job_card_callbacks_fit_64_bytes():
    big = 2_147_483_647
    datas = [b.callback_data for row in rider_offer_kb(big).inline_keyboard for b in row]
    datas += [b.callback_data for row in rider_job_card_kb(big).inline_keyboard for b in row]
    assert len(datas) == 5 and all(1 <= len(d.encode()) <= 64 for d in datas)
    assert fits_callback_limit(RiderJobAction(d=big, a="cc")) and fits_callback_limit(RiderOffer(d=big, a="d"))
    assert [b.text for row in rider_job_card_kb(1).inline_keyboard for b in row] == [v[0] for v in JOB_CARD_ACTIONS.values()]


# ---- offer taps ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "outcome, accept, edited",
    [
        (dispatch_actions.ACCEPTED, True, "👍 Accepted · <b>ELAS-ABCD-1</b>\nWaiting for confirmation…"),
        (dispatch_actions.DECLINED, False, "Declined · <b>ELAS-ABCD-1</b>"),
        (dispatch_actions.TAKEN, True, "❌ Taken by another rider · <b>ELAS-ABCD-1</b>"),
        (dispatch_actions.GONE, True, "This job is no longer available · <b>ELAS-ABCD-1</b>"),
        (dispatch_actions.ALREADY_ON_THIS_JOB, True, "✅ The job is yours · <b>ELAS-ABCD-1</b>"),
        (dispatch_actions.CANCEL_OWN_JOB, False, "🚫 Order cancelled · <b>ELAS-ABCD-1</b>"),
    ],
)
async def test_offer_tap_applies_the_shared_rules_and_edits_the_offer(recording_bot, linked, offers, outcome, accept, edited):
    bot, session = recording_bot
    offers.outcome = outcome
    await feed(bot, callback_update(RiderOffer(d=7, a="a" if accept else "d").pack()))
    assert offers.calls == [(PHONE, 7, ORDER, accept)]
    edits = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert [(e.text, e.chat_id, e.message_id, e.reply_markup) for e in edits] == [(edited, 111, 10, None)]


async def test_offer_tap_ignored_outcome_leaves_the_offer_alone(recording_bot, linked, offers):
    bot, session = recording_bot
    offers.outcome = dispatch_actions.IGNORED
    await feed(bot, callback_update(RiderOffer(d=7, a="a").pack()))
    assert offers.calls and session.edited_texts == []


async def test_offer_tap_by_someone_not_linked_is_refused(recording_bot, rider_db, offers):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderOffer(d=7, a="a").pack()))
    assert offers.calls == [] and session.answers == [(jobs.NOT_LINKED, True)]


async def test_offer_tap_on_another_riders_offer_is_refused(recording_bot, rider_db, offers):
    bot, session = recording_bot
    rider_db.add("447700900999", tuid=111, tcid=111)  # the tapper is a different rider
    await feed(bot, callback_update(RiderOffer(d=7, a="a").pack()))
    assert offers.calls == [] and session.answers == [(jobs.NOT_YOURS, True)]


async def test_offer_tap_on_a_vanished_offer_says_gone(recording_bot, linked, offers):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderOffer(d=99, a="a").pack()))
    assert offers.calls == [] and session.edited_texts == ["This job is no longer available"]


async def test_offer_tap_when_the_db_is_down_says_try_again(recording_bot, linked, offers):
    bot, session = recording_bot
    offers.fail = True
    await feed(bot, callback_update(RiderOffer(d=7, a="a").pack()))
    assert offers.calls == [] and session.answers == [(jobs.TROUBLE, True)]


# ---- job-card taps -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action", ["pk", "dr", "cc"])
async def test_job_card_tap_reaches_the_agent_with_the_whatsapp_words(recording_bot, linked, threads, spawned, action):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderJobAction(d=7, a=action).pack()))
    runs = await spawned()
    assert runs == [("run_rider_agent_w_custom_msg", (PHONE,),
                     {"human_msg": JOB_CARD_ACTIONS[action][1], "thread_id": "ORDELO-dispatch-7"})]
    assert session.answers == [(None, False)]


async def test_job_card_tap_on_a_closed_or_finished_job_says_expired(recording_bot, linked, threads, spawned):
    bot, session = recording_bot
    threads.by_dispatch[7] = RiderThread("ORDELO-dispatch-7", PHONE, is_active=False, dispatch_id=7)
    await feed(bot, callback_update(RiderJobAction(d=7, a="pk").pack()))
    threads.by_dispatch[8] = None
    await feed(bot, callback_update(RiderJobAction(d=8, a="pk").pack(), update_id=3))
    assert await spawned() == []
    assert [a[0] for a in session.answers] == [jobs.EXPIRED, jobs.EXPIRED]


async def test_job_card_tap_on_another_riders_job_is_refused(recording_bot, rider_db, threads, spawned):
    bot, session = recording_bot
    rider_db.add("447700900999", tuid=111, tcid=111)
    await feed(bot, callback_update(RiderJobAction(d=7, a="cc").pack()))
    assert await spawned() == [] and session.answers == [(jobs.NOT_YOURS, True)]


# ---- /job ----------------------------------------------------------------------------------------------------------
async def test_job_command_shows_the_current_job(recording_bot, linked, threads, monkeypatch):
    bot, session = recording_bot

    async def summary(order_number):
        return {"order_number": order_number, "pickup_time": None, "rest_name": "Elas", "rest_address": "1 High St",
                "customer_address": "2 Low Rd"}

    monkeypatch.setattr(jobs, "_order_summary", summary)
    await feed(bot, message_update("/job"))
    assert session.sent_texts == ["<b>Current job: ELAS-ABCD-1</b>\n🏠 Elas, 1 High St\n📍 Drop-off: 2 Low Rd"]
    assert threads.touched == [False]  # /job never keeps a thread alive


async def test_job_command_without_a_job(recording_bot, linked, threads):
    bot, session = recording_bot
    threads.active = None
    await feed(bot, message_update("/job"))
    assert session.sent_texts == [jobs.NO_JOB]


async def test_job_command_for_a_whatsapp_job_points_there(recording_bot, linked, threads, monkeypatch):
    bot, session = recording_bot
    threads.active = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number=ORDER, channel="whatsapp")

    async def summary(order_number):
        return None

    monkeypatch.setattr(jobs, "_order_summary", summary)
    await feed(bot, message_update("/job"))
    assert session.sent_texts == ["<b>Current job: ELAS-ABCD-1</b>\nYour current job ELAS-ABCD-1 is on WhatsApp. Please reply there."]


# ---- text ----------------------------------------------------------------------------------------------------------
async def test_text_on_a_telegram_job_runs_the_agent_in_the_background(recording_bot, linked, threads, spawned):
    bot, session = recording_bot
    await feed(bot, message_update("I'm at the restaurant"))
    runs = await spawned()
    assert runs == [("run_rider_agent", (threads.active,),
                     {"human_msg": "I'm at the restaurant", "state_update_dict": {"latest_wa_msg_id": "tg:111:10"}})]
    assert [type(c) for c in session.calls] == [SendChatAction]  # the reply comes from the agent, not the handler


async def test_text_on_a_whatsapp_job_points_there(recording_bot, linked, threads, spawned):
    bot, session = recording_bot
    threads.active = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number=ORDER, channel="whatsapp")
    await feed(bot, message_update("hello"))
    assert await spawned() == []
    assert session.sent_texts == ["Your current job <b>ELAS-ABCD-1</b> is on WhatsApp. Please reply there."]


async def test_text_from_someone_not_linked_asks_for_start(recording_bot, rider_db, threads, spawned):
    bot, session = recording_bot
    await feed(bot, message_update("hello"))
    assert await spawned() == []
    assert len(session.sent_texts) == 1 and all(isinstance(c, SendMessage) for c in session.calls)


async def test_unknown_command_from_a_linked_rider(recording_bot, linked, threads, spawned):
    bot, session = recording_bot
    await feed(bot, message_update("/whatever"))
    assert await spawned() == []
    assert session.sent_texts == ["I don't know that command. Try /help."]
