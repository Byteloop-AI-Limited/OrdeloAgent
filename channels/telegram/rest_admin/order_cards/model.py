"""The order card: one immutable value, changed only by events, composed in one place.

Pure (no I/O, no aiogram calls): `Card.view(viewer)` is the ONLY place an admin-facing order
text, button or toast is built. See plans/telegram-rest-admin-scaffold-plan.md "The order card"
(D26) and docs/telegram-layer.md.

`Status` keys are the SQL `t_order_card_status()` keys (create_t_order_alerts.sql). Change both
together.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from html import escape
from typing import Literal

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from utils_common.tz_utils import fmt_uk_time, parse_db_iso

from ...callbacks import OrderAction

OrderType = Literal["delivery", "takeaway"]
Status = Literal["awaiting", "accepted", "pickup_set", "declined", "auto_accepted", "gone"]
TERMINAL: frozenset[str] = frozenset({"pickup_set", "declined", "auto_accepted", "gone"})
PICKUP_MINUTES: tuple[int, ...] = (5, 15, 25)  # parity with wa_senders.send_restaurant_pickup_time

TROUBLE = "Sorry, something went wrong on our side. Please try again in a minute."  # imported by rest_admin/router.py
NO_ACCESS = "🔒 You no longer have access to this restaurant's orders."
GONE_TEXT = "This order is no longer available."


@dataclass(frozen=True)
class OrderRef:
    """Identifies one order: the number plus which summary table it lives in."""

    order_number: str
    order_type: OrderType


@dataclass(frozen=True)
class Facts:
    order_number: str
    order_type: OrderType
    rest_name: str
    total: str
    items: tuple[str, ...]
    ordered_at: datetime


@dataclass(frozen=True)
class Actor:
    label: str  # "Ada" | "…0754"
    phone: str | None  # matched against the viewer's phone to say "You"


@dataclass(frozen=True)
class Reminded:
    n: int
    of: int


@dataclass(frozen=True)
class Accepted:
    by: Actor


@dataclass(frozen=True)
class Declined:
    by: Actor


@dataclass(frozen=True)
class PickupChosen:
    at: datetime
    by: Actor | None


@dataclass(frozen=True)
class AutoAccepted:
    at: datetime


@dataclass(frozen=True)
class Vanished:
    pass


Event = Reminded | Accepted | Declined | PickupChosen | AutoAccepted | Vanished


@dataclass(frozen=True)
class Viewer:
    phone: str | None
    authorised: bool = True
    shared: bool = False  # D27: group chat -> third-person text; buttons for any authorised tapper


@dataclass(frozen=True)
class View:
    text: str
    keyboard: InlineKeyboardMarkup | None
    terminal: bool


@dataclass(frozen=True)
class Snapshot:
    """What `t_order_card_snapshot` returns, parsed. `facts` is None when the order is gone."""

    status: Status
    facts: Facts | None
    decided_by: Actor | None = None
    pickup_at: datetime | None = None
    destinations: tuple["Destination", ...] = ()
    rest_ref: str = ""

    @classmethod
    def from_json(cls, data: dict | None) -> "Snapshot | None":
        if not data:
            return None
        f = data["facts"]
        facts = Facts(
            order_number=f["order_number"],
            order_type=f["order_type"],
            rest_name=f.get("rest_name") or "",
            total=f.get("total") or "",
            items=tuple(f.get("items") or ()),
            ordered_at=parse_db_iso(f["ordered_at"]),
        )
        by = data.get("decided_by")
        pickup = data.get("pickup_at")
        return cls(
            status=data["status"],
            rest_ref=data.get("rest_ref") or "",
            facts=facts,
            decided_by=Actor(by.get("label") or "", by.get("phone")) if by else None,
            pickup_at=parse_db_iso(pickup) if pickup else None,
            destinations=tuple(
                Destination(tcid=d["tcid"], tuid=d.get("tuid"), phone=d.get("phone"), label=d.get("label"))
                for d in data.get("destinations") or ()
            ),
        )


@dataclass(frozen=True)
class Destination:
    tcid: int  # chat to send to / edit
    tuid: int | None  # admin it belongs to; None = shared (group) chat
    phone: str | None
    label: str | None = None


# restaurant_confirmation_status -> card status key, for the "already decided" answers of the decision RPCs.
# Mirrors t_order_card_status() in create_t_order_alerts.sql (only the states a lost race can report).
_STATE_TO_STATUS = {
    "restaurant_accept": "accepted",
    "restaurant_pickuptime_adjusted": "pickup_set",
    "restaurant_decline": "declined",
    "auto_decline": "declined",
    "auto_accept": "auto_accepted",
    "restaurant_timedout": "auto_accepted",
}
_RESULTS = ("ok", "already_decided", "already_set", "not_accepted", "not_authorised", "not_found")


@dataclass(frozen=True)
class TapOutcome:
    """Result of a tap, parsed from t_order_decide / t_order_set_pickup (restaurant_order_decision.sql)."""

    result: Literal["ok", "already_decided", "already_set", "not_accepted", "not_authorised", "not_found"]
    action: Literal["acc", "dec", "pk"]
    status: str | None = None  # card status key the order is in now, for already_decided / already_set
    by: Actor | None = None  # who decided (for "Already accepted by Ada")
    pickup_at: datetime | None = None

    @classmethod
    def from_rpc(cls, action: Literal["acc", "dec", "pk"], data: object) -> "TapOutcome":
        if not isinstance(data, dict) or data.get("result") not in _RESULTS:
            raise RuntimeError(f"unexpected order tap RPC response: {data!r}")
        label, phone = data.get("decided_by"), data.get("decided_by_phone")
        pickup = data.get("pickup_time")
        return cls(
            result=data["result"],
            action=action,
            status=_STATE_TO_STATUS.get(data.get("state") or ""),
            by=Actor(label or "", phone) if (label or phone) else None,
            pickup_at=parse_db_iso(pickup) if isinstance(pickup, str) else None,
        )


def _type_line(t: OrderType) -> str:
    return "🚚 Delivery" if t == "delivery" else "🥡 Takeaway"


@dataclass(frozen=True)
class Card:
    facts: Facts
    status: Status = "awaiting"
    reminder: tuple[int, int] | None = None
    decided_by: Actor | None = None
    pickup_at: datetime | None = None

    # ---- events -------------------------------------------------------------------------
    def apply(self, event: Event) -> "Card":
        s = self.status
        if isinstance(event, Vanished):
            return replace(self, status="gone")
        if isinstance(event, Reminded) and s == "awaiting":
            return replace(self, reminder=(event.n, event.of))
        if isinstance(event, Accepted) and s == "awaiting":
            return replace(self, status="accepted", decided_by=event.by)
        if isinstance(event, Declined) and s == "awaiting":
            return replace(self, status="declined", decided_by=event.by)
        if isinstance(event, AutoAccepted) and s in ("awaiting", "accepted"):
            return replace(self, status="auto_accepted", pickup_at=event.at)
        if isinstance(event, PickupChosen) and s == "accepted":
            return replace(
                self, status="pickup_set", pickup_at=event.at, decided_by=event.by or self.decided_by
            )
        logger.debug(f"order card {self.facts.order_number}: ignored {type(event).__name__} in {s}")
        return self

    @classmethod
    def from_snapshot(cls, snap: Snapshot) -> "Card":
        if snap.facts is None or snap.status == "gone":
            raise ValueError("gone snapshot has no facts; use Card.vanished(facts)")
        card = cls(snap.facts)
        by, at = snap.decided_by, snap.pickup_at
        if snap.status == "accepted" and by:
            return card.apply(Accepted(by))
        if snap.status == "pickup_set" and by and at:
            return card.apply(Accepted(by)).apply(PickupChosen(at, by))
        if snap.status == "declined" and by:
            return card.apply(Declined(by))
        if snap.status == "auto_accepted" and at:
            return card.apply(AutoAccepted(at))
        if snap.status != "awaiting":
            # a status without the data that status needs: show the safest known state
            logger.error(f"order card {snap.facts.order_number}: incomplete snapshot for {snap.status}")
        return card

    @classmethod
    def vanished(cls, facts: Facts) -> "Card":
        return cls(facts).apply(Vanished())

    # ---- views --------------------------------------------------------------------------
    def _who(self, viewer: Viewer) -> str:
        by = self.decided_by
        if by is None:
            return "an admin"
        if not viewer.shared and viewer.phone is not None and by.phone == viewer.phone:
            return "You"
        return by.label

    def _is_decider(self, viewer: Viewer) -> bool:
        return (
            not viewer.shared
            and viewer.phone is not None
            and self.decided_by is not None
            and self.decided_by.phone == viewer.phone
        )

    def _status_line(self, viewer: Viewer) -> str:
        me = self._is_decider(viewer)
        who = escape(self._who(viewer))
        pk = f" · pickup {fmt_uk_time(self.pickup_at)}" if self.pickup_at else ""
        match self.status:
            case "awaiting":
                n = self.reminder
                extra = f" · reminder {n[0]} of {n[1]}" if n and n[0] > 1 else ""
                return f"🔔 New order — accept or decline{extra}"
            case "accepted":
                return (
                    "✅ You accepted — choose a pickup time"
                    if me
                    else f"✅ Accepted by {who} — waiting for pickup time"
                )
            case "pickup_set":
                return f"✅ You accepted{pk}" if me else f"✅ Accepted by {who}{pk}"
            case "declined":
                return "❌ You declined this order" if me else f"❌ Declined by {who}"
            case "auto_accepted":
                return f"⏱ Auto-accepted (no answer in time){pk}"
            case _:
                return GONE_TEXT

    def _body(self) -> str:
        f = self.facts
        lines = [f"<b>{escape(f.order_number)}</b> · {escape(f.total)} · {_type_line(f.order_type)}"]
        lines += [escape(i) for i in f.items]
        lines.append(f"Ordered {fmt_uk_time(f.ordered_at)}")
        return "\n".join(lines)

    def _keyboard(self, viewer: Viewer) -> InlineKeyboardMarkup | None:
        f = self.facts
        t = "d" if f.order_type == "delivery" else "t"
        kb = InlineKeyboardBuilder()
        try:
            if self.status == "awaiting":
                kb.button(text="✅ Accept", callback_data=OrderAction(o=f.order_number, t=t, a="acc").pack())
                kb.button(text="❌ Decline", callback_data=OrderAction(o=f.order_number, t=t, a="dec").pack())
                kb.adjust(2)
            elif self.status == "accepted" and (self._is_decider(viewer) or viewer.shared):
                for m in PICKUP_MINUTES:
                    at = f.ordered_at + timedelta(minutes=m)
                    data = OrderAction(o=f.order_number, t=t, a="pk", m=m).pack()
                    kb.button(text=fmt_uk_time(at), callback_data=data)
                kb.adjust(len(PICKUP_MINUTES))
            else:
                return None
        except ValueError:  # aiogram refuses callback data over 64 bytes (or with ':' in the number)
            logger.error(f"order card {f.order_number}: callback data invalid, buttons dropped")
            return None
        return kb.as_markup()

    def view(self, viewer: Viewer) -> View:
        if not viewer.authorised:
            return View(NO_ACCESS, None, True)
        if self.status == "gone":
            return View(GONE_TEXT, None, True)
        text = f"{self._status_line(viewer)}\n{self._body()}"
        return View(text, self._keyboard(viewer), self.status in TERMINAL)


def toast(outcome: TapOutcome) -> tuple[str, bool]:
    """(callback answer text, show_alert)."""
    r = outcome.result
    if r == "ok":
        if outcome.action == "acc":
            return "Accepted — pick a time", False
        if outcome.action == "dec":
            return "Declined", False
        return (f"Pickup {fmt_uk_time(outcome.pickup_at)}" if outcome.pickup_at else "Pickup time set"), False
    if r == "already_decided":
        who = outcome.by.label if outcome.by else "an admin"
        word = {
            "declined": "declined",
            "auto_accepted": "auto-accepted",
        }.get(outcome.status or "", "accepted")
        return (f"Already {word}" if word == "auto-accepted" else f"Already {word} by {who}"), False
    if r == "already_set":
        at = f" to {fmt_uk_time(outcome.pickup_at)}" if outcome.pickup_at else ""
        return f"Pickup already set{at}", False
    if r == "not_accepted":
        return "This order is not accepted yet.", False
    if r == "not_authorised":
        return "You're not an admin for this restaurant any more.", True
    return GONE_TEXT, False
