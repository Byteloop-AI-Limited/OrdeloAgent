"""Offline helpers for Telegram adapter tests: a recording Bot API session and update builders."""

from __future__ import annotations

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, SendMessage, SendRichMessage
from aiogram.types import Message


class RecordingSession(BaseSession):
    """Captures outgoing Bot API calls and returns minimal valid results. No network."""

    def __init__(self):
        super().__init__()
        self.calls: list = []
        self.closed = False
        self.next_message_id = 1000
        # Set to a callable(method) -> Exception | None to make chosen Bot API calls fail (offline error mapping tests).
        self.fail = None

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.fail is not None:
            err = self.fail(method)
            if err is not None:
                raise err
        if isinstance(method, (SendMessage, SendRichMessage)):
            self.next_message_id += 1
            return Message.model_validate(
                {
                    "message_id": self.next_message_id,
                    "date": 0,
                    "chat": {"id": method.chat_id, "type": "private"},
                    "text": getattr(method, "text", None),
                },
                context={"bot": bot},
            )
        return True

    async def close(self):
        self.closed = True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        if False:
            yield b""

    @property
    def sent_texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, SendMessage)]

    @property
    def edited_texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, EditMessageText)]

    @property
    def answers(self) -> list[tuple[str | None, bool | None]]:
        return [(c.text, c.show_alert) for c in self.calls if isinstance(c, AnswerCallbackQuery)]

    @property
    def deleted(self) -> list[tuple[int, int]]:
        return [(c.chat_id, c.message_id) for c in self.calls if isinstance(c, DeleteMessage)]

    @property
    def edits(self) -> list:
        return [c for c in self.calls if isinstance(c, EditMessageText)]

    @property
    def sends(self) -> list:
        return [c for c in self.calls if isinstance(c, SendMessage)]

    @property
    def last_keyboard(self):
        sent = [c for c in self.calls if isinstance(c, SendMessage)]
        return sent[-1].reply_markup if sent else None


@pytest.fixture
def recording_bot():
    session = RecordingSession()
    return Bot(token="123456:TEST-token", session=session), session


def message_update(text: str, user_id: int = 111, update_id: int = 1, username: str = "ada") -> dict:
    is_cmd = text.startswith("/")
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10,
            "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": username},
            "text": text,
            **({"entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]} if is_cmd else {}),
        },
    }


def callback_update(data: str, user_id: int = 111, update_id: int = 2, username: str = "ada",
                    chat_id: int | None = None, message_id: int = 10) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "chat_instance": "ci",
            "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": username},
            "message": {
                "message_id": message_id,
                "date": 1_700_000_000,
                "chat": ({"id": chat_id, "type": "supergroup", "title": "Kitchen"} if chat_id is not None
                         else {"id": user_id, "type": "private"}),
                "text": "Link this chat?",
            },
        },
    }


class FakeResp:
    def __init__(self, data):
        self.data = data


class FakeInviteDb:
    """In-memory mimic of the three t_* invite SQL functions (same result vocabulary and rules)."""

    def __init__(self):
        self.invites: dict[str, dict] = {}
        self.restaurants = {"ELAS": "Ela's Kitchen", "WREN": "Wren <Cafe>"}
        self.rpc_names: list[str] = []

    def add(self, code="CODE12345678", rest_ref="ELAS", bot_key="rest_admin", status="pending"):
        self.invites[code] = dict(code=code, rest_ref=rest_ref, bot_key=bot_key, status=status, uid=None, cid=None,
                                  username=None, first_name=None)
        return code

    def _preview(self, a):
        r = self.invites.get(a["p_code"])
        if not r or r["bot_key"] != a["p_bot_key"]:
            return {"result": "unknown"}
        res = ("revoked" if r["status"] == "revoked"
               else "claimed_by_you" if r["status"] == "claimed" and r["uid"] == a["p_user_id"]
               else "used" if r["status"] == "claimed"
               else "expired" if r["status"] == "expired"
               else "pending")
        return {"result": res, "rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}

    def _claim(self, a):
        r = self.invites.get(a["p_code"])
        if r and r["bot_key"] == a["p_bot_key"] and r["status"] == "pending":
            if any(o["status"] == "claimed" and o["uid"] == a["p_user_id"] and o["rest_ref"] == r["rest_ref"]
                   for o in self.invites.values()):
                return {"result": "already_linked"}
            r.update(status="claimed", uid=a["p_user_id"], cid=a["p_chat_id"],
                     username=a["p_username"], first_name=a["p_first_name"])
            return {"result": "ok", "rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}
        return self._preview(a)

    def _linked(self, a):
        return [{"rest_ref": r["rest_ref"], "rest_name": self.restaurants[r["rest_ref"]]}
                for r in self.invites.values()
                if r["status"] == "claimed" and r["uid"] == a["p_user_id"] and r["bot_key"] == a["p_bot_key"]]

    def rpc(self, name, args=None):
        self.rpc_names.append(name)
        fn = {"t_invite_preview": self._preview, "t_claim_invite": self._claim,
              "t_linked_restaurants": self._linked}[name]
        data = fn(args or {})
        return type("Q", (), {"execute": lambda self_: FakeResp(data)})()


@pytest.fixture
def invite_db(monkeypatch):
    db = FakeInviteDb()
    monkeypatch.setattr("channels.telegram.invites.client_ordelo_service", db)
    return db


class FakeInboxDb:
    """In-memory mimic of t_inbox_claim / t_inbox_finish (same result vocabulary and rules)."""

    def __init__(self):
        self.rows: dict[tuple[str, int], dict] = {}
        self.rpc_names: list[str] = []
        self.fail_claim = False
        self.fail_finish = False

    def _claim(self, a):
        if self.fail_claim:
            raise RuntimeError("inbox db down")
        key = (a["p_bot_key"], a["p_update_id"])
        if key in self.rows:
            return {"result": "duplicate", "status": self.rows[key]["status"]}
        self.rows[key] = dict(kind=a["p_kind"], tuid=a["p_tuid"], status="processing", error=None)
        return {"result": "new"}

    def _finish(self, a):
        if self.fail_finish:
            raise RuntimeError("inbox db down")
        if a["p_status"] not in ("done", "failed"):
            raise ValueError("bad status")
        row = self.rows.get((a["p_bot_key"], a["p_update_id"]))
        if not row or row["status"] != "processing":
            return {"result": "not_processing"}
        row.update(status=a["p_status"], error=(a.get("p_error") or None) and a["p_error"][:2000])
        return {"result": "ok"}

    def rpc(self, name, args=None):
        self.rpc_names.append(name)
        data = {"t_inbox_claim": self._claim, "t_inbox_finish": self._finish}[name](args or {})
        return type("Q", (), {"execute": lambda self_: FakeResp(data)})()

    def status_of(self, update_id: int, bot_key: str = "rest_admin") -> str | None:
        row = self.rows.get((bot_key, update_id))
        return row["status"] if row else None


@pytest.fixture
def inbox_db(monkeypatch):
    db = FakeInboxDb()
    monkeypatch.setattr("channels.telegram.inbox.client_ordelo_service", db)
    return db


# ---- order cards ----------------------------------------------------------------------------------------------


class FakeCardStore:
    """In-memory mimic of telegram/t_order_alerts.sql as seen through CardStore (same rules and vocabulary).

    orders:  order_number -> Snapshot-shaped dict (status, facts, decided_by, pickup_at, rest_ref, destinations)
    ledger:  list of dict rows like t_sent_messages (id, tcid, message_id, tuid, order_number, card_status, state, taken_for, ...)
    Change this fake whenever the SQL functions change.
    """

    def __init__(self):
        from channels.telegram.rest_admin.order_cards.model import Destination  # noqa: F401  (imported lazily)

        self.orders: dict[str, dict] = {}
        self.ledger: list[dict] = []
        self.calls: list[str] = []
        self.on_card_sent = None  # callable(store, order, dest): lets a test decide the order "mid-send"
        self._next_id = 1

    # ---- test helpers
    def add_order(self, order_number="ELAS-CEKT-22", order_type="delivery", status="awaiting", destinations=None,
                  decided_by=None, pickup_at=None, rest_ref="ELAS"):
        from datetime import datetime, timezone

        from channels.telegram.rest_admin.order_cards.model import Destination, Facts, OrderRef

        self.orders[order_number] = dict(
            status=status, rest_ref=rest_ref, decided_by=decided_by, pickup_at=pickup_at,
            facts=Facts(order_number, order_type, "Elas", "£23.50", ("2x Biryani", "1x Naan"),
                        datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)),
            destinations=tuple(destinations if destinations is not None else [Destination(111, 111, "447700900001", "Ada")]),
        )
        return OrderRef(order_number, order_type)

    def set_status(self, order_number, status, decided_by=None, pickup_at=None):
        o = self.orders[order_number]
        o.update(status=status, decided_by=decided_by or o["decided_by"], pickup_at=pickup_at or o["pickup_at"])

    def rows(self, state=None):
        return [r for r in self.ledger if state is None or r["state"] == state]

    # ---- phase 5: mimic t_order_decide / t_order_set_pickup (restaurant_order_decision.sql)
    # admins: tuid -> Actor for people with a claimed invite whose phone is in restaurant_master.admins (D14)
    admins: dict = {}

    def _auth(self, tuid, order):
        o = self.orders.get(order.order_number)
        if o is None:
            return None, {"result": "not_found"}
        who = self.admins.get(tuid)
        if who is None:
            return o, {"result": "not_authorised"}
        return o, None

    async def decide(self, tuid, order, decision):
        from channels.telegram.rest_admin.order_cards.model import TapOutcome

        self.calls.append(f"decide:{decision}")
        action = "acc" if decision == "accept" else "dec"
        o, early = self._auth(tuid, order)
        if early:
            return TapOutcome.from_rpc(action, early)
        who = self.admins[tuid]
        if o["status"] == "awaiting":
            self.set_status(order.order_number, "accepted" if decision == "accept" else "declined", who)
            return TapOutcome.from_rpc(action, {"result": "ok", "decided_by": who.label, "decided_by_phone": who.phone})
        state = {"accepted": "restaurant_accept", "pickup_set": "restaurant_accept", "declined": "restaurant_decline",
                 "auto_accepted": "auto_accept"}[o["status"]]
        by = o["decided_by"]
        return TapOutcome.from_rpc(action, {"result": "already_decided", "state": state,
                                            "decided_by": by.label if by else None,
                                            "decided_by_phone": by.phone if by else None})

    async def set_pickup(self, tuid, order, minutes):
        from datetime import timedelta

        from channels.telegram.rest_admin.order_cards.model import TapOutcome

        self.calls.append(f"set_pickup:{minutes}")
        o, early = self._auth(tuid, order)
        if early:
            return TapOutcome.from_rpc("pk", early)
        who = self.admins[tuid]
        if o["status"] == "accepted":
            at = o["facts"].ordered_at + timedelta(minutes=minutes)
            self.set_status(order.order_number, "pickup_set", who, at)
            return TapOutcome.from_rpc("pk", {"result": "ok", "pickup_time": at.isoformat(), "decided_by": who.label,
                                              "decided_by_phone": who.phone})
        res = "already_set" if o["status"] in ("pickup_set", "auto_accepted") else "not_accepted"
        by = o["decided_by"]
        return TapOutcome.from_rpc("pk", {"result": res, "state": "restaurant_accept",
                                          "pickup_time": o["pickup_at"].isoformat() if o["pickup_at"] else None,
                                          "decided_by": by.label if by else None, "decided_by_phone": by.phone if by else None})

    # ---- CardStore interface
    async def snapshot(self, order):
        from channels.telegram.rest_admin.order_cards.model import Snapshot

        self.calls.append("snapshot")
        o = self.orders.get(order.order_number)
        if o is None:
            return None
        return Snapshot(status=o["status"], facts=o["facts"], decided_by=o["decided_by"], pickup_at=o["pickup_at"],
                        destinations=o["destinations"], rest_ref=o["rest_ref"])

    async def card_sent(self, order, rest_ref, dest, message_id, card_status):
        from channels.telegram.rest_admin.order_cards.store import CardCopy, SentRecord

        self.calls.append("card_sent")
        row = dict(id=self._next_id, tcid=dest.tcid, message_id=message_id, tuid=dest.tuid, order_number=order.order_number,
                   order_type=order.order_type, rest_ref=rest_ref, card_status=card_status, state="live", taken_for=None,
                   reoffer=False, close_reason=None)
        self._next_id += 1
        self.ledger.append(row)
        prev = [r for r in self.ledger if r["tcid"] == dest.tcid and r["order_number"] == order.order_number
                and r["state"] == "live" and r["id"] < row["id"]]
        for r in prev:
            r.update(state="taken", taken_for="delete")
        if self.on_card_sent:
            self.on_card_sent(self, order, dest)
        o = self.orders.get(order.order_number)
        return SentRecord(tuple(CardCopy(r["id"], r["tcid"], r["message_id"], taken_for="delete") for r in prev),
                          o["status"] if o else "gone")

    async def take_for_refresh(self, order):
        from channels.telegram.rest_admin.order_cards.store import CardCopy

        self.calls.append("take")
        o = self.orders.get(order.order_number)
        current = o["status"] if o else "gone"
        out = []
        for r in self.ledger:
            if r["order_number"] != order.order_number:
                continue
            # SQL resolves a copy's destination from the ledger's rest_ref, so a vanished order keeps its viewers authorised
            dests = {d.tcid: d for d in o["destinations"]} if o else {r["tcid"]: None}
            d = dests.get(r["tcid"])
            authorised = o is None or d is not None
            stale_live = r["state"] == "live" and (r["card_status"] != current or not authorised)
            reoffer = r["state"] == "taken" and r["reoffer"]
            if stale_live or reoffer:
                if r["state"] == "live":
                    r["taken_for"] = "edit"
                r["state"] = "taken"
                r["reoffer"] = False
                out.append(CardCopy(r["id"], r["tcid"], r["message_id"], r["tuid"], d.phone if d else None,
                                    authorised, r["taken_for"]))
        return out

    async def mark(self, copy_id, outcome, card_status, close):
        self.calls.append(f"mark:{outcome}")
        r = next(x for x in self.ledger if x["id"] == copy_id)
        if r["state"] != "taken":
            return
        if close or outcome in ("deleted", "gone"):
            r.update(state="closed", close_reason=outcome, taken_for=None, card_status=card_status or r["card_status"])
        else:
            r.update(state="live", card_status=card_status, taken_for=None)


@pytest.fixture
def card_store():
    from channels.telegram.rest_admin.order_cards.model import Actor

    store = FakeCardStore()
    store.admins = {111: Actor("Ada", "447700900001"), 222: Actor("Bob", "447700900002")}  # instance copy, not class state
    return store
