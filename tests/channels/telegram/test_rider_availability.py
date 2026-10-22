"""The rider bot's availability commands (phase R5), driven through a real Dispatcher offline: /off (+ break-length taps), /on,
/shift. channels/telegram/rider/availability.py.

The domain calls are faked at their seams with the SQL result vocabulary: ordelo.pauses (pause_start / pause_end /
pause_current / pause_options, proven in tests/sql/test_pauses_sql.py), ordelo.rider_shift (rider_set_shift,
tests/sql/test_rider_shift_sql.py) and rider_threads (the current job). Identity comes from FakeRiderDb (t_rider_profile).
Scenario rows (telegram-vertification-loop): allowed actor, not linked, not active, stale option, DB down, callbacks within
64 bytes, menu and help list the commands.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from aiogram.methods import EditMessageText
from aiogram.types import Update

from channels.telegram.bots import build_rider_dispatcher
from channels.telegram.callbacks import RiderPause, fits_callback_limit
from channels.telegram.keyboards import pause_duration_kb
from channels.telegram.rider import availability
from channels.telegram.rider.commands import HELP_TEXT, RIDER_COMMANDS
from config.tgram_setting import TgramBotSettings
from ordelo import pauses, rider_shift
from ordelo.agents.rider_threads import RiderThread

from .conftest import callback_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot("rider", {"tgram_rider_bot_token": "654321:TEST-rider", "tgram_rider_webhook_secret": "abc"})
PHONE = "447700900511"
ENDS = datetime(2026, 10, 23, 17, 30, tzinfo=timezone.utc)


async def feed(bot, payload: dict):
    dp = build_rider_dispatcher(SETTINGS)
    await dp.feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


@pytest.fixture
def rider(rider_db):
    return rider_db.add(PHONE, tuid=111, tcid=111)


@pytest.fixture
def domain(monkeypatch):
    """In-memory pauses + shift rule + current job, with the SQL result vocabulary."""

    class Domain:
        keys = ["6h", "1d", "3d"]
        paused_until: datetime | None = None
        shift_result = rider_shift.ON
        job: RiderThread | None = None
        calls: list[tuple] = []
        fail = False

    d = Domain()
    d.calls = []

    def check():
        if d.fail:
            raise RuntimeError("db down")

    async def options(audience):
        check()
        d.calls.append(("options", audience))
        return list(d.keys)

    async def current(audience, principal, *, scope=None):
        check()
        return pauses.Pause(1, d.paused_until) if d.paused_until else None

    async def pause(audience, principal, duration, *, scope=None, via="telegram", by=None):
        check()
        d.calls.append(("pause", audience, principal, duration, via, by))
        if duration not in d.keys:
            return pauses.PauseOutcome("bad_duration")
        result = "extended" if d.paused_until else "paused"
        d.paused_until = ENDS
        return pauses.PauseOutcome(result, pauses.Pause(1, ENDS))

    async def resume(audience, principal, *, scope=None, operator=False):
        check()
        d.calls.append(("resume", audience, principal))
        was, d.paused_until = d.paused_until, None
        return pauses.PauseOutcome("resumed" if was else "not_paused")

    async def set_shift(rider_id, on):
        check()
        d.calls.append(("set_shift", rider_id, on))
        return rider_shift.ShiftOutcome(d.shift_result, status="inactive" if d.shift_result == rider_shift.NOT_ACTIVE else None)

    async def active_for_rider(rider_id, touch=True):
        d.calls.append(("job", touch))
        return d.job

    monkeypatch.setattr(availability.pauses, "options", options)
    monkeypatch.setattr(availability.pauses, "current", current)
    monkeypatch.setattr(availability.pauses, "pause", pause)
    monkeypatch.setattr(availability.pauses, "resume", resume)
    monkeypatch.setattr(availability.rider_shift, "set_shift", set_shift)
    monkeypatch.setattr(availability.rider_threads, "active_for_rider", active_for_rider)
    return d


def until() -> str:
    return pauses.ends_text(ENDS)


# ---- menu ----------------------------------------------------------------------------------------------------------
def test_menu_and_help_list_the_r5_commands():
    names = [c.command for c in RIDER_COMMANDS]
    assert {"shift", "off", "on"} <= set(names) and all(f"/{n}" in HELP_TEXT for n in ("shift", "off", "on"))


def test_break_length_buttons_fit_and_skip_what_cannot_be_packed():
    kb = pause_duration_kb(["6h", "1d", "3d", "x:y"])
    buttons = [b for row in kb.inline_keyboard for b in row]
    assert [(b.text, b.callback_data) for b in buttons] == [("6 hours", "rp1:6h"), ("1 day", "rp1:1d"), ("3 days", "rp1:3d")]
    assert fits_callback_limit(RiderPause(k="999d"))


# ---- /off ----------------------------------------------------------------------------------------------------------
async def test_off_offers_the_configured_lengths(recording_bot, rider, domain):
    bot, session = recording_bot
    await feed(bot, message_update("/off"))
    assert session.sent_texts == [availability.ASK_LENGTH]
    assert [b.callback_data for row in session.last_keyboard.inline_keyboard for b in row] == ["rp1:6h", "rp1:1d", "rp1:3d"]


async def test_off_while_on_a_break_says_until_when(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.paused_until = ENDS
    await feed(bot, message_update("/off"))
    assert session.sent_texts[0].startswith(f"You're on a break until <b>{until()}</b>.")


@pytest.mark.parametrize("setup, expected", [
    ("not_linked", availability.NOT_LINKED),
    ("inactive", availability.NOT_ACTIVE),
    ("no_keys", availability.OFF_DISABLED),
    ("db_down", availability.TROUBLE),
])
async def test_off_refusals(recording_bot, rider_db, domain, setup, expected):
    bot, session = recording_bot
    if setup != "not_linked":
        rider_db.add(PHONE, status="inactive" if setup == "inactive" else "active", tuid=111, tcid=111)
    domain.keys = [] if setup == "no_keys" else domain.keys
    domain.fail = setup == "db_down"
    await feed(bot, message_update("/off"))
    assert session.sent_texts == [expected]
    assert session.last_keyboard is None


# ---- a break-length tap --------------------------------------------------------------------------------------------
async def test_tap_starts_the_break_and_edits_the_question(recording_bot, rider, domain):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderPause(k="1d").pack()))
    assert ("pause", "rider", PHONE, "1d", "telegram", "111") in domain.calls
    edits = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert [(e.text, e.reply_markup) for e in edits] == [(availability.paused_text(ENDS), None)]
    assert session.answers == [(None, False)]


async def test_redelivered_tap_after_on_is_acknowledged_without_restarting_break(recording_bot, rider, domain, inbox_db):
    bot, session = recording_bot
    tap = callback_update(RiderPause(k="1d").pack(), update_id=2)
    await feed(bot, tap)
    await feed(bot, message_update("/on", update_id=3))
    await feed(bot, tap)

    assert domain.paused_until is None
    assert len([call for call in domain.calls if call[0] == "pause"]) == 1
    assert len(session.edited_texts) == 1
    assert session.answers == [(None, False), (None, False)]
    assert inbox_db.status_of(2, "rider") == "done"


async def test_tap_during_a_job_says_the_job_carries_on(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.job = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number="ELAS-ABCD-1", channel="telegram")
    await feed(bot, callback_update(RiderPause(k="6h").pack()))
    assert session.edited_texts[0].endswith("Your current job <b>ELAS-ABCD-1</b> (/job) carries on.")
    assert ("job", False) in domain.calls  # looking at the job never keeps its thread alive


async def test_tap_with_a_length_no_longer_allowed(recording_bot, rider, domain):
    bot, session = recording_bot
    await feed(bot, callback_update(RiderPause(k="9d").pack()))
    assert session.edited_texts == [availability.OPTION_GONE]


@pytest.mark.parametrize("status, expected", [(None, availability.NOT_LINKED), ("inactive", availability.NOT_ACTIVE)])
async def test_tap_by_someone_who_cannot_take_a_break(recording_bot, rider_db, domain, status, expected):
    bot, session = recording_bot
    if status:
        rider_db.add(PHONE, status=status, tuid=111, tcid=111)
    await feed(bot, callback_update(RiderPause(k="6h").pack()))
    assert session.edited_texts == [expected] and not [c for c in domain.calls if c[0] == "pause"]


# ---- /on -----------------------------------------------------------------------------------------------------------
async def test_on_ends_the_break_and_switches_the_shift_on(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.paused_until = ENDS
    await feed(bot, message_update("/on"))
    assert session.sent_texts == [availability.BACK_ON]
    assert ("resume", "rider", PHONE) in domain.calls and ("set_shift", PHONE, True) in domain.calls


async def test_on_when_already_on(recording_bot, rider, domain):
    bot, session = recording_bot
    await feed(bot, message_update("/on"))
    assert session.sent_texts == [availability.ALREADY_ON]


async def test_on_for_a_rider_who_is_not_active(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.shift_result = rider_shift.NOT_ACTIVE
    await feed(bot, message_update("/on"))
    assert session.sent_texts == [availability.NOT_ACTIVE]


async def test_on_for_a_rider_whose_offers_go_to_whatsapp(recording_bot, rider, domain):
    bot, session = recording_bot
    rider["channel"] = "whatsapp"
    await feed(bot, message_update("/on"))
    assert session.sent_texts == [availability.ALREADY_ON + "\n" + availability.OTHER_CHANNEL]


# ---- /shift --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("state, expected", [
    ("on", "🟢 On: new job offers arrive here. Send /off to take a break."),
    ("paused", None),
    ("off_shift", "⚪ Off shift. Send /on to start getting job offers."),
    ("inactive", "⚪ " + availability.NOT_ACTIVE),
])
async def test_shift_says_why_offers_do_or_do_not_arrive(recording_bot, rider, domain, state, expected):
    bot, session = recording_bot
    if state == "paused":
        domain.paused_until = ENDS
        expected = f"⏸ On a break until <b>{until()}</b>. Send /on to come back early."
    rider["is_in_shift"] = state != "off_shift"
    rider["status"] = "inactive" if state == "inactive" else "active"
    await feed(bot, message_update("/shift"))
    assert session.sent_texts == [expected]


async def test_shift_shows_the_current_job(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.job = RiderThread("ORDELO-dispatch-7", PHONE, dispatch_id=7, order_number="ELAS-ABCD-1", channel="telegram")
    await feed(bot, message_update("/shift"))
    assert session.sent_texts[0].endswith("\nCurrent job: <b>ELAS-ABCD-1</b> (/job)")


async def test_shift_when_the_db_is_down(recording_bot, rider, domain):
    bot, session = recording_bot
    domain.fail = True
    await feed(bot, message_update("/shift"))
    assert session.sent_texts == [availability.TROUBLE]


def test_paused_text_reads_naturally():
    soon = datetime.now(timezone.utc) + timedelta(hours=2)
    text = availability.paused_text(soon, "Current job: <b>X</b> (/job)")
    assert text.splitlines()[0].startswith("⏸ On a break until <b>") and text.splitlines()[-1] == "Your current job <b>X</b> (/job) carries on."
