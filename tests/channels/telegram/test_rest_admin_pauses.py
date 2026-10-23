"""Restaurant-bot alert pauses (phase R6), driven through a real Dispatcher offline: /off (+ length taps) and /on.
channels/telegram/rest_admin/pauses.py over channels/telegram/admin_pauses.py.

FakeAdminPauseDb mimics the t_admin_* RPCs (telegram/t_admin_pauses.sql) with the same result vocabulary, including the
last-admin guard of pause_start (proven against Postgres in tests/sql/test_admin_pauses_sql.py). Scenario rows: allowed
actor, not linked, last admin, stale option, DB down, the wrapper's argument names and shapes, the text fallback no longer
swallowing commands, callbacks within 64 bytes.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiogram.methods import EditMessageText
from aiogram.types import Update

from channels.telegram import admin_pauses
from channels.telegram.bots import build_rest_admin_dispatcher
from channels.telegram.callbacks import AdminPause, fits_callback_limit
from channels.telegram.keyboards import pause_duration_kb
from channels.telegram.rest_admin import pauses as rest_pauses
from channels.telegram.rest_admin.commands import HELP_TEXT, REST_ADMIN_COMMANDS
from config.tgram_setting import TgramBotSettings
from ordelo.pauses import ends_text

from .conftest import FakeResp, callback_update, message_update

pytestmark = pytest.mark.usefixtures("inbox_db")

SETTINGS = TgramBotSettings.for_bot(
    "rest_admin", {"tgram_rest_admin_bot_token": "123456:TEST-token", "tgram_rest_admin_webhook_secret": "abc"}
)
ADA, BOB = "447700900811", "447700900812"
ENDS = "2026-10-23T17:30:00+00:00"


class FakeAdminPauseDb:
    """In-memory mimic of t_admin_pause / t_admin_resume / t_admin_pause_status / t_admin_pause_chats."""

    def __init__(self):
        self.restaurants = {"ELAS": ("Elas Kitchen", [ADA, BOB]), "WREN": ("Wren", [ADA])}
        self.links: dict[int, list[tuple[str, str]]] = {}  # tuid -> [(rest_ref, phone)]
        self.chats: dict[tuple[str, str], list[int]] = {}  # (phone, rest_ref) -> tcids
        self.paused: set[tuple[str, str]] = set()
        self.keys = ["6h", "1d", "3d"]
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def link(self, tuid, phone, *rests):
        self.links[tuid] = [(r, phone) for r in rests]
        for r in rests:
            self.chats.setdefault((phone, r), []).append(tuid)

    def _mine(self, a):
        return sorted(self.links.get(a["p_tuid"], []))

    def _pause(self, a):
        out = []
        for rest, phone in self._mine(a):
            name, admins = self.restaurants[rest]
            if a["p_duration"] not in self.keys:
                result = "bad_duration"
            elif not any(o != phone and (o, rest) not in self.paused for o in admins):
                result = "not_allowed"
            else:
                result = "extended" if (phone, rest) in self.paused else "paused"
                self.paused.add((phone, rest))
            out.append({"rest_ref": rest, "rest_name": name, "result": result,
                        "ends_at": ENDS if result in ("paused", "extended") else None})
        return {"result": "ok", "restaurants": out} if out else {"result": "not_linked"}

    def _resume(self, a):
        out = []
        for rest, phone in self._mine(a):
            was = (phone, rest) in self.paused
            self.paused.discard((phone, rest))
            out.append({"rest_ref": rest, "rest_name": self.restaurants[rest][0], "result": "resumed" if was else "not_paused"})
        return {"result": "ok", "restaurants": out} if out else {"result": "not_linked"}

    def _status(self, a):
        rows = [{"rest_ref": r, "rest_name": self.restaurants[r][0], "paused": (p, r) in self.paused,
                 "ends_at": ENDS if (p, r) in self.paused else None} for r, p in self._mine(a)]
        return {"result": "ok", "options": list(self.keys), "restaurants": rows} if rows else {"result": "not_linked"}

    def _chats(self, a):
        return [{"tcid": t, "rest_name": self.restaurants[a["p_rest_ref"]][0]} for t in self.chats.get((a["p_phone"], a["p_rest_ref"]), [])]

    def rpc(self, name, args):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((name, dict(args)))
        fn = {"t_admin_pause": self._pause, "t_admin_resume": self._resume, "t_admin_pause_status": self._status,
              "t_admin_pause_chats": self._chats}[name]
        data = fn(args)
        return type("Q", (), {"execute": lambda self_: FakeResp(data)})()


@pytest.fixture
def adb(monkeypatch):
    db = FakeAdminPauseDb()
    monkeypatch.setattr("channels.telegram.admin_pauses.client_ordelo_service", db)
    return db


async def feed(bot, payload: dict):
    await build_rest_admin_dispatcher(SETTINGS).feed_update(bot, Update.model_validate(payload, context={"bot": bot}))


def until() -> str:
    return ends_text(datetime.fromisoformat(ENDS))


# ---- menu, keyboard ------------------------------------------------------------------------------------------------
def test_menu_and_help_list_off_and_on():
    assert {"off", "on"} <= {c.command for c in REST_ADMIN_COMMANDS} and "/off" in HELP_TEXT and "/on" in HELP_TEXT


def test_length_buttons_are_admin_callbacks_within_64_bytes():
    kb = pause_duration_kb(["6h", "1d"], admin=True)
    assert [b.callback_data for row in kb.inline_keyboard for b in row] == ["ap1:6h", "ap1:1d"]
    assert fits_callback_limit(AdminPause(k="999d"))


# ---- /off ----------------------------------------------------------------------------------------------------------
async def test_off_shows_each_restaurant_and_the_lengths(recording_bot, adb):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS", "WREN")
    adb.paused.add((ADA, "ELAS"))
    await feed(bot, message_update("/off"))
    assert session.sent_texts == ["\n".join([rest_pauses.ASK_LENGTH, f"⏸ <b>Elas Kitchen</b>: paused until {until()}",
                                             "🔔 <b>Wren</b>: alerts on", rest_pauses.TELEGRAM_ONLY])]
    assert [b.callback_data for row in session.last_keyboard.inline_keyboard for b in row] == ["ap1:6h", "ap1:1d", "ap1:3d"]
    assert adb.calls == [("t_admin_pause_status", {"p_bot_key": "rest_admin", "p_tuid": 111})]


@pytest.mark.parametrize("setup, expected", [("not_linked", rest_pauses.NOT_LINKED), ("no_keys", rest_pauses.OFF_DISABLED),
                                             ("db_down", "trouble")])
async def test_off_refusals(recording_bot, adb, setup, expected):
    bot, session = recording_bot
    if setup != "not_linked":
        adb.link(111, ADA, "ELAS")
    adb.keys = [] if setup == "no_keys" else adb.keys
    adb.fail = setup == "db_down"
    await feed(bot, message_update("/off"))
    assert session.sent_texts == [rest_pauses.TROUBLE if expected == "trouble" else expected]
    assert session.last_keyboard is None


# ---- a length tap --------------------------------------------------------------------------------------------------
async def test_tap_pauses_where_allowed_and_explains_the_last_admin_rule(recording_bot, adb):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS", "WREN")
    await feed(bot, callback_update(AdminPause(k="1d").pack()))
    edits = [c for c in session.calls if isinstance(c, EditMessageText)]
    assert [(e.text, e.reply_markup) for e in edits] == [("\n".join([
        f"⏸ <b>Elas Kitchen</b>: paused until {until()}",
        "🔔 <b>Wren</b>: not paused. You're the only admin left getting its alerts.",
        rest_pauses.COME_BACK,
    ]), None)]
    assert adb.calls == [("t_admin_pause", {"p_bot_key": "rest_admin", "p_tuid": 111, "p_duration": "1d"})]


async def test_redelivered_tap_after_on_is_acknowledged_without_restarting_pause(recording_bot, adb, inbox_db):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS")
    tap = callback_update(AdminPause(k="1d").pack(), update_id=2)
    await feed(bot, tap)
    await feed(bot, message_update("/on", update_id=3))
    await feed(bot, tap)

    assert adb.paused == set()
    assert len([name for name, _ in adb.calls if name == "t_admin_pause"]) == 1
    assert len(session.edited_texts) == 1
    assert session.answers == [(None, False), (None, False)]
    assert inbox_db.status_of(2) == "done"


async def test_the_second_admin_cannot_pause_while_the_first_is_paused(recording_bot, adb):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS")
    adb.link(222, BOB, "ELAS")
    await feed(bot, callback_update(AdminPause(k="6h").pack(), user_id=111))
    await feed(bot, callback_update(AdminPause(k="6h").pack(), user_id=222, update_id=3))
    assert session.edited_texts[-1] == "🔔 <b>Elas Kitchen</b>: not paused. You're the only admin left getting its alerts."


async def test_tap_with_a_length_no_longer_allowed(recording_bot, adb):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS")
    await feed(bot, callback_update(AdminPause(k="9d").pack()))
    assert session.edited_texts == [rest_pauses.OPTION_GONE]


async def test_tap_by_someone_not_linked(recording_bot, adb):
    bot, session = recording_bot
    await feed(bot, callback_update(AdminPause(k="6h").pack()))
    assert session.edited_texts == [rest_pauses.NOT_LINKED]


# ---- /on -----------------------------------------------------------------------------------------------------------
async def test_on_turns_alerts_back_on(recording_bot, adb):
    bot, session = recording_bot
    adb.link(111, ADA, "ELAS", "WREN")
    adb.paused.add((ADA, "ELAS"))
    await feed(bot, message_update("/on"))
    assert session.sent_texts == ["🔔 <b>Elas Kitchen</b>: alerts back on\n🔔 <b>Wren</b>: alerts were already on"]
    assert adb.paused == set()


async def test_on_not_linked_and_db_down(recording_bot, adb):
    bot, session = recording_bot
    await feed(bot, message_update("/on"))
    adb.fail = True
    await feed(bot, message_update("/on", update_id=2))
    assert session.sent_texts == [rest_pauses.NOT_LINKED, rest_pauses.TROUBLE]


async def test_text_fallback_still_answers_plain_text(recording_bot, adb):
    bot, session = recording_bot
    await feed(bot, message_update("hello"))
    assert "Try /help" in session.sent_texts[0] and adb.calls == []


# ---- the wrapper ---------------------------------------------------------------------------------------------------
async def test_wrapper_shapes_and_chats(adb):
    adb.link(111, ADA, "ELAS")
    st = await admin_pauses.status("rest_admin", 111)
    assert st.is_linked and st.options == ("6h", "1d", "3d")
    assert st.restaurants == (admin_pauses.RestaurantPause("ELAS", "Elas Kitchen", None, False, None),)
    out = await admin_pauses.pause("rest_admin", 111, "6h")
    assert out.restaurants[0].ends_at == datetime(2026, 10, 23, 17, 30, tzinfo=timezone.utc)
    assert await admin_pauses.chats("rest_admin", ADA, "ELAS") == [(111, "Elas Kitchen")]
    assert adb.calls[-1] == ("t_admin_pause_chats", {"p_bot_key": "rest_admin", "p_phone": ADA, "p_rest_ref": "ELAS"})
    assert (await admin_pauses.resume("rest_admin", 999)).result == "not_linked"


@pytest.mark.parametrize("data", [None, {"result": "weird"}, []])
async def test_wrapper_rejects_unexpected_responses(monkeypatch, data):
    class Bad:
        def rpc(self, name, args):
            return type("Q", (), {"execute": lambda s: FakeResp(data)})()

    monkeypatch.setattr("channels.telegram.admin_pauses.client_ordelo_service", Bad())
    with pytest.raises(RuntimeError):
        await admin_pauses.status("rest_admin", 111)
