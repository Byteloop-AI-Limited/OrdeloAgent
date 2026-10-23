"""The kitchen receipt: one immutable value, composed in one place (pure: no I/O, no aiogram calls).

`Receipt.view(viewer)` is the ONLY place a receipt's text or buttons are built; `receipt_toast` the only place its
toasts are. The status keys are the SQL `t_receipt_status()` keys (ordelo_datamodels/migrations/
restaurant_ready_adjust_notices.sql section 5); the database decides them, Python only reads them. Change both together:
    delivery: gone | done | rider_cancelled | picked_up | ready@HH:MI | open@HH:MI
    takeaway: gone | done | ready@HH:MI | open@HH:MI          (HH:MI = pickup time in Europe/London)
Layout approved with the owner (plan section 5.5); the live-location link is left out on purpose (no longer functional).
Two forms of the same content: the HTML text + inline keyboard (`View.text`, `View.keyboard`) and a rich message
(`View.rich`: a status badge coloured by state, the progress flow as one disabled button per step, buttons embedded). TelegramIO
tries the rich form first and falls back to the HTML form if Telegram rejects it. Nothing is stored about who has seen what.
Two decisions are made once and read by BOTH forms (plans/telegram-receipt-phases-plan.md): `Receipt.phase` ("kitchen" while the food
is being made, "handed_over" once picked up / collected) and `Receipt.timeline(viewer)` (every step: done, latest, still to come).
In the handed-over phase the order itself (pickup time, code, items, money, notes, customer) folds into a closed "Order details" block.
  Classes/Functions:
    . ReceiptDestination, ReceiptFacts, Line, Step, ReceiptSnapshot
    . Receipt
    . receipt_toast
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Literal

from aiogram.types import (
    DisabledButton, InlineKeyboardMarkup, InputRichBlockButtons, InputRichBlockDetails, InputRichBlockParagraph,
    InputRichBlockSectionHeading, InputRichMessage, RichMessageButton, RichTextBold, RichTextItalic,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from utils_common.order_management.restaurant_actions import ActionOutcome
from utils_common.tz_utils import fmt_uk_time, parse_db_iso

from ...callbacks import OrderAction
from ..order_cards.model import GONE_TEXT, NO_ACCESS, Actor, View, Viewer

OrderType = Literal["delivery", "takeaway"]
Phase = Literal["kitchen", "handed_over"]
StepState = Literal["done", "latest", "todo", "failed"]
ADJUST_STEPS: tuple[int, ...] = (10, 20)
TEXT_LIMIT = 4000        # Telegram allows 4096 characters; the rest is a safety margin for entity parsing
NOTES_LIMIT = 600
NOT_ADMIN = "You're not an admin for this restaurant any more."
TERMINAL_KINDS: frozenset[str] = frozenset({"gone", "done", "rider_cancelled"})  # nothing more will ever change
UP_TO_DATE = "Up to date"  # toast for a tap on the status badge
HANDED_OVER_KINDS: frozenset[str] = frozenset({"picked_up", "done"})  # D55: the food has left the kitchen
STEP_STYLES: dict[str, str | None] = {"done": None, "latest": "success", "todo": None, "failed": "danger"}  # D56
STEP_MARKS = {"done": "✓ ", "latest": "● ", "todo": "🔒 ", "failed": ""}
ORDER_DETAILS = "🔵 Order details · tap to expand"  # Telegram cannot colour summary text; the blue dot marks it as a folded block
FLOW_ROWS_IN_DETAILS = True  # D57: kitchen-phase flow rows inside the closed Progress block; False = text lines (live spike decides)
BADGE_STYLES = {"open": "primary", "ready": "success", "picked_up": "success", "done": "success", "rider_cancelled": "danger"}


def status_kind(key: str) -> str:
    """'ready@12:50' -> 'ready'; 'done' -> 'done'."""
    return key.partition("@")[0]


@dataclass(frozen=True)
class Line:
    qty: float
    name: str
    line_total: float | None
    mods: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    """One row of the progress flow. `label` is plain text; the HTML renderer escapes it."""

    label: str
    state: StepState
    at: datetime | None = None

    def text(self) -> str:
        """'✓ ✅ Accepted by Ada · 9:02 AM' | '● 🍳 Ready by You · 9:35 AM' | '🔒 🛵 Rider picks up · pending'."""
        tail = " · pending" if self.state == "todo" else (f" · {fmt_uk_time(self.at)}" if self.at else "")
        return f"{STEP_MARKS[self.state]}{self.label}{tail}"


@dataclass(frozen=True)
class ReceiptFacts:
    order_number: str
    order_type: OrderType
    rest_name: str
    rest_code: int | None
    pickup_at: datetime | None
    pickup_initial: datetime | None
    pickup_adjusted_by: Actor | None
    ready_at: datetime | None
    ready_by: Actor | None
    rider_id: str | None
    rider_name: str | None
    customer_address: str | None
    customer_phone: str | None
    items: tuple[Line, ...]
    small_order_fee: float | None
    total: float | None
    notes: str | None
    pay_at_restaurant: bool
    completed_at: datetime | None
    # D58: who accepted, and when. Defaults keep snapshots from a database without the new keys working.
    accepted_by: Actor | None = None
    accepted_at: datetime | None = None
    accepted_auto: bool = False


@dataclass(frozen=True)
class ReceiptDestination:
    tcid: int
    tuid: int | None          # None = shared (group) chat
    phone: str | None
    label: str | None = None
    reply_to: int | None = None   # newest existing order-card copy in that chat, so the receipt threads under it


def _actor(d: dict | None) -> Actor | None:
    return Actor(d.get("label") or "", d.get("phone")) if d else None


def _when(v: str | None) -> datetime | None:
    return parse_db_iso(v) if v else None


@dataclass(frozen=True)
class ReceiptSnapshot:
    """What `t_receipt_snapshot` returns, parsed. The status is the key for THIS dispatch."""

    status: str
    rest_ref: str
    dispatch_id: int | None
    facts: ReceiptFacts
    destinations: tuple[ReceiptDestination, ...] = ()

    @classmethod
    def from_json(cls, data: dict | None) -> "ReceiptSnapshot | None":
        if not data:
            return None
        f = data["facts"]
        rider = f.get("rider") or {}
        customer = f.get("customer") or {}
        facts = ReceiptFacts(
            order_number=f["order_number"],
            order_type=f["order_type"],
            rest_name=f.get("rest_name") or "",
            rest_code=f.get("rest_code"),
            pickup_at=_when(f.get("pickup_at")),
            pickup_initial=_when(f.get("pickup_initial")),
            pickup_adjusted_by=_actor(f.get("pickup_adjusted_by")),
            ready_at=_when(f.get("ready_at")),
            ready_by=_actor(f.get("ready_by")),
            rider_id=rider.get("id"),
            rider_name=rider.get("name"),
            customer_address=customer.get("address"),
            customer_phone=customer.get("phone"),
            items=tuple(
                Line(i.get("qty") or 1, i.get("name") or "", i.get("line_total"), tuple(i.get("mods") or ()))
                for i in f.get("items") or ()
            ),
            small_order_fee=f.get("small_order_fee"),
            total=f.get("total"),
            notes=f.get("notes"),
            pay_at_restaurant=bool(f.get("pay_at_restaurant")),
            completed_at=_when(f.get("completed_at")),
            accepted_by=_actor(f.get("accepted_by")),
            accepted_at=_when(f.get("accepted_at")),
            accepted_auto=bool(f.get("accepted_auto")),
        )
        return cls(
            status=data["status"] or "gone",
            rest_ref=data.get("rest_ref") or "",
            dispatch_id=data.get("dispatch_id"),
            facts=facts,
            destinations=tuple(
                ReceiptDestination(d["tcid"], d.get("tuid"), d.get("phone"), d.get("label"), d.get("reply_to"))
                for d in data.get("destinations") or ()
            ),
        )


def _money(v: float | None) -> str:
    return f"£{float(v):.2f}" if v is not None else "—"


def _qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:g}"


@dataclass(frozen=True)
class Receipt:
    status: str
    facts: ReceiptFacts

    @classmethod
    def from_snapshot(cls, snap: ReceiptSnapshot) -> "Receipt":
        return cls(snap.status, snap.facts)

    @property
    def kind(self) -> str:
        return status_kind(self.status)

    # ---- pieces -------------------------------------------------------------------------
    def _who_plain(self, actor: Actor | None, viewer: Viewer) -> str:
        if actor is None:
            return "an admin"
        if not viewer.shared and viewer.phone is not None and actor.phone == viewer.phone:
            return "You"
        return actor.label or "an admin"

    def _who(self, actor: Actor | None, viewer: Viewer) -> str:
        return escape(self._who_plain(actor, viewer))

    def _status_line(self, viewer: Viewer) -> str | None:
        f = self.facts
        match self.kind:
            case "ready":
                # The database knows who marked it ready, not whether the message to the rider / customer got through
                # (the tapper is told that in the toast), so this line claims only what is recorded.
                by = f" by {self._who(f.ready_by, viewer)}" if f.ready_by else ""
                return f"✅ Marked ready{by}"
            case "picked_up":
                return "🛵 Picked up by the rider"
            case "done":
                if f.order_type == "takeaway":
                    return "✅ Collected"
                at = f" {fmt_uk_time(f.completed_at)}" if f.completed_at else ""
                return f"✅ Delivered{at}"
            case "rider_cancelled":
                return "⚠️ This rider is no longer on the job"
            case _:
                return None

    def _moved(self, viewer: Viewer, who) -> str:
        """' (moved +10 by Ada)' when the pickup was moved from the original time, else ''. `who` names the actor."""
        f = self.facts
        if f.pickup_at is None or f.pickup_initial is None or f.pickup_initial == f.pickup_at:
            return ""
        mins = round((f.pickup_at - f.pickup_initial).total_seconds() / 60)
        by = f" by {who(f.pickup_adjusted_by, viewer)}" if f.pickup_adjusted_by else ""
        return f" (moved {mins:+d}{by})"

    def _pickup_line(self, viewer: Viewer) -> str:
        f = self.facts
        if f.pickup_at is None:
            return "⏰ Pickup: —"
        return f"⏰ Pickup: <b>{fmt_uk_time(f.pickup_at)}</b>{self._moved(viewer, self._who)}"

    def _item_block(self, i: Line) -> str:
        lines = [f"• {_qty(i.qty)} × {escape(i.name)} — {_money(i.line_total)}"]
        lines += [f"   ↳ {escape(m)}" for m in i.mods]
        return "\n".join(lines)

    def _title_lines(self, viewer: Viewer) -> list[str]:
        f = self.facts
        kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
        lines = [f"🧾 KITCHEN RECEIPT · {kind}", f"<b>{escape(f.order_number)}</b>"]
        if status := self._status_line(viewer):
            lines.append(status)
        return lines

    def _code_line(self) -> str:
        code = self.facts.rest_code
        return f"🔑 Restaurant code: <b>{code if code is not None else '—'}</b>"

    def _rider_line(self) -> str | None:
        f = self.facts
        if f.order_type != "delivery" or not (f.rider_name or f.rider_id):
            return None
        who = escape(f.rider_name or f.rider_id or "")
        return f"🛵 Rider: {who}" + (f" — {escape(f.rider_id)}" if f.rider_name and f.rider_id else "")

    def _head(self, viewer: Viewer) -> str:
        """Kitchen phase: title, number, status, code, pickup, rider."""
        lines = self._title_lines(viewer) + [self._code_line(), self._pickup_line(viewer)]
        if rider := self._rider_line():
            lines.append(rider)
        return "\n".join(lines)

    @staticmethod
    def _flow_html(steps: tuple["Step", ...]) -> str:
        return "\n".join(
            f"<b>{escape(s.text())}</b>" if s.state in ("latest", "failed") else escape(s.text()) for s in steps
        )

    def _tail(self) -> str:
        f = self.facts
        parts: list[str] = []
        money = []
        if f.small_order_fee:
            money.append(f"Small order fee: {_money(f.small_order_fee)}")
        money.append(f"<b>Total: {_money(f.total)}</b>")
        parts.append("\n".join(money))
        if f.pay_at_restaurant:
            parts.append(f"💷 <b>Pay at restaurant — collect {_money(f.total)}</b>")
        if f.notes and f.notes.strip():
            note = f.notes.strip()
            note = note[:NOTES_LIMIT] + "…" if len(note) > NOTES_LIMIT else note
            parts.append(f"📝 <b>Notes</b>\n<i>{escape(note)}</i>")
        if f.order_type == "delivery" and (f.customer_address or f.customer_phone):
            bits = [escape(b) for b in (f.customer_address, f.customer_phone) if b]
            parts.append("🏠 Customer: " + " — ".join(bits))
        return "\n\n".join(parts)

    def _fit(self, viewer: Viewer) -> tuple[str, int]:
        """The HTML text, and how many items it shows. The rich form shows the same items."""
        tail = self._tail()
        blocks = [self._item_block(i) for i in self.facts.items]
        steps = self.timeline(viewer)
        handed_over = self.phase == "handed_over"
        if handed_over:
            rider = self._rider_line()
            top = "\n".join(self._title_lines(viewer)) + "\n\n" + self._flow_html(steps) + (f"\n{rider}" if rider else "")
            folded = f"{self._code_line()}\n{self._pickup_line(viewer)}"
        else:
            head = self._head(viewer)
            progress = (
                f"<blockquote expandable><b>{escape(self._progress_summary(steps))}</b>\n{self._flow_html(steps)}</blockquote>"
                if steps else ""
            )

        def build(n: int) -> str:
            shown = blocks[:n]
            if n < len(blocks):
                shown.append(f"… and {len(blocks) - n} more items (see WhatsApp/printer)")
            items = "<b>Items</b>\n" + ("\n".join(shown) if shown else "—")
            if handed_over:  # D59/D60: the order folded into one expandable quote (a blockquote cannot nest)
                return f"{top}\n\n<blockquote expandable><b>{ORDER_DETAILS}</b>\n{folded}\n\n{items}\n\n{tail}</blockquote>"
            return "\n\n".join(p for p in (head, progress, items, tail) if p)

        for n in range(len(blocks), -1, -1):
            text = build(n)
            if len(text) <= TEXT_LIMIT:
                return text, n
        return text, 0  # even without items too long (cannot happen: notes are capped); sent as is

    def _compose(self, viewer: Viewer) -> str:
        return self._fit(viewer)[0]

    def _actions(self) -> list[list[tuple[str, OrderAction]]]:
        """The kitchen buttons as rows of (label, action): one source for the inline keyboard and the rich message."""
        f = self.facts
        t = "d" if f.order_type == "delivery" else "t"
        base = f.pickup_initial or f.pickup_at
        rows: list[list[tuple[str, OrderAction]]] = []
        if self.kind == "open":
            label = "🍳 Ready – notify rider" if f.order_type == "delivery" else "🍳 Ready for collection"
            rows.append([(label, OrderAction(o=f.order_number, t=t, a="rdy"))])
        if f.order_type == "delivery" and self.kind in ("open", "ready") and base is not None:
            rows.append([
                (f"{fmt_uk_time(base + timedelta(minutes=m))} (+{m})", OrderAction(o=f.order_number, t=t, a="adj", m=m))
                for m in ADJUST_STEPS
            ])
        return rows

    def _keyboard(self, viewer: Viewer) -> InlineKeyboardMarkup | None:
        rows = self._actions()
        if not rows:
            return None
        kb = InlineKeyboardBuilder()
        try:
            for row in rows:
                for label, action in row:
                    kb.button(text=label, callback_data=action.pack())
        except ValueError:  # aiogram refuses callback data over 64 bytes (or with ':' in the number)
            logger.error(f"receipt {self.facts.order_number}: callback data invalid, buttons dropped")
            return None
        kb.adjust(*(len(row) for row in rows))
        return kb.as_markup()

    # ---- the two decisions every renderer reads ------------------------------------------------------------------------
    @property
    def phase(self) -> Phase:
        """'handed_over' once the food has left the kitchen (D55); the full kitchen layout otherwise."""
        return "handed_over" if self.kind in HANDED_OVER_KINDS else "kitchen"

    def _accepted_label(self, viewer: Viewer) -> str:
        f = self.facts
        if f.accepted_auto:
            return "✅ Accepted automatically"
        if f.accepted_by is not None:
            return f"✅ Accepted by {self._who_plain(f.accepted_by, viewer)}"
        return "✅ Accepted"  # snapshot from a database without the accepted keys

    def _reached(self, total: int) -> int:
        """How many steps have happened, from the status key alone (the database decides the key)."""
        match self.kind:
            case "open":
                return 2  # accepted + pickup time set
            case "ready":
                return 3
            case "picked_up":
                return 4
            case "done":
                return total
            case "rider_cancelled":
                return 3 if self.facts.ready_at else 2
            case _:
                return 0  # 'gone' never reaches the renderers

    def timeline(self, viewer: Viewer) -> tuple[Step, ...]:
        """Every step in order: done (grey ✓), latest (green), still to come (grey 🔒); a cancelled rider ends it in red."""
        f = self.facts
        rider = f.rider_name or f.rider_id
        ready_by = f" by {self._who_plain(f.ready_by, viewer)}" if f.ready_by else ""
        pickup = (f"⏰ Pickup {fmt_uk_time(f.pickup_at)}{self._moved(viewer, self._who_plain)}"
                  if f.pickup_at else "⏰ Pickup time")
        # (label once it has happened, label while still to come, when it happened)
        rows: list[tuple[str, str, datetime | None]] = [
            (self._accepted_label(viewer), "✅ Accepted", f.accepted_at),
            (pickup, pickup, None),
            (f"🍳 Ready{ready_by}" if f.ready_at else "🍳 Ready (not marked)", "🍳 Food ready", f.ready_at),
        ]
        if f.order_type == "delivery":
            rows.append((f"🛵 Picked up by {rider}" if rider else "🛵 Picked up", "🛵 Rider picks up", None))
            rows.append(("🏁 Delivered", "🏁 Delivered", f.completed_at))
        else:
            rows.append(("🏁 Collected", "🏁 Collected", f.completed_at))
        reached, cancelled = self._reached(len(rows)), self.kind == "rider_cancelled"
        steps: list[Step] = []
        for i, (done, todo, at) in enumerate(rows):
            if i < reached:
                steps.append(Step(done, "latest" if i == reached - 1 and not cancelled else "done", at))
            elif not cancelled:
                steps.append(Step(todo, "todo"))
        if cancelled:
            steps.append(Step("⚠️ This rider is no longer on the job", "failed"))
        return tuple(steps)

    @staticmethod
    def _progress_summary(steps: tuple[Step, ...]) -> str:
        if any(s.state == "failed" for s in steps):
            return "Progress · rider no longer on the job"
        happened = sum(s.state in ("done", "latest") for s in steps)
        return f"Progress · step {happened} of {len(steps)}"

    # ---- the rich form: status badge, progress flow, embedded buttons --------------------------------------------------
    def _badge_text(self, viewer: Viewer) -> str:
        f = self.facts
        match self.kind:
            case "open":
                return f"📋 Preparing · pickup {fmt_uk_time(f.pickup_at)}" if f.pickup_at else "📋 Preparing"
            case "ready":
                by = f" by {self._who_plain(f.ready_by, viewer)}" if f.ready_by else ""
                return f"✅ Marked ready{by}"
            case "picked_up":
                return "🛵 Picked up by the rider"
            case "done":
                if f.order_type == "takeaway":
                    return "✅ Collected"
                return f"✅ Delivered {fmt_uk_time(f.completed_at)}" if f.completed_at else "✅ Delivered"
            case _:
                return "⚠️ This rider is no longer on the job"

    def _badge(self, viewer: Viewer) -> RichMessageButton:
        """Coloured by state. While the order can still change, tapping it redraws the copies from the database."""
        text, style = self._badge_text(viewer), BADGE_STYLES.get(self.kind)
        if self.kind not in TERMINAL_KINDS:
            f = self.facts
            t = "d" if f.order_type == "delivery" else "t"
            try:
                data = OrderAction(o=f.order_number, t=t, a="st").pack()
                return RichMessageButton(text=text, style=style, callback_data=data)
            except ValueError:
                logger.error(f"receipt {f.order_number}: status badge callback data invalid, badge not tappable")
        return RichMessageButton(text=text, style=style, disabled=DisabledButton())

    def _flow_rows(self, steps: tuple[Step, ...]) -> list[InputRichBlockButtons]:
        """One disabled button per step (D56): the flow is a picture, never an action."""
        return [
            InputRichBlockButtons(buttons=[
                RichMessageButton(text=s.text(), style=STEP_STYLES[s.state], disabled=DisabledButton())
            ])
            for s in steps
        ]

    def _progress(self, viewer: Viewer) -> InputRichBlockDetails | None:
        """Kitchen phase: the flow inside a closed native block (D57)."""
        steps = self.timeline(viewer)
        if not steps:
            return None
        inner = (self._flow_rows(steps) if FLOW_ROWS_IN_DETAILS
                 else [InputRichBlockParagraph(text=s.text()) for s in steps])
        return InputRichBlockDetails(summary=self._progress_summary(steps), is_open=False, blocks=inner)

    def _rich_actions(self) -> list[InputRichBlockButtons]:
        try:
            return [
                InputRichBlockButtons(buttons=[
                    RichMessageButton(
                        text=label, style="success" if action.a == "rdy" else "primary", callback_data=action.pack()
                    )
                    for label, action in row
                ])
                for row in self._actions()
            ]
        except ValueError:
            logger.error(f"receipt {self.facts.order_number}: callback data invalid, rich buttons dropped")
            return []

    def _rich_head(self, viewer: Viewer) -> list:
        f = self.facts
        kind = "🚚 Delivery" if f.order_type == "delivery" else "🥡 Takeaway"
        return [
            InputRichBlockSectionHeading(text=f"🧾 Kitchen receipt · {kind}", size=3),
            InputRichBlockParagraph(text=RichTextBold(text=f.order_number)),
            InputRichBlockButtons(buttons=[self._badge(viewer)]),
        ]

    def _rich_pickup(self, viewer: Viewer) -> InputRichBlockParagraph:
        f = self.facts
        if f.pickup_at is None:
            return InputRichBlockParagraph(text="⏰ Pickup: —")
        return InputRichBlockParagraph(text=[
            "⏰ Pickup: ", RichTextBold(text=fmt_uk_time(f.pickup_at)), self._moved(viewer, self._who_plain),
        ])

    def _rich_code(self) -> InputRichBlockParagraph:
        code = self.facts.rest_code
        return InputRichBlockParagraph(text=f"🔑 Restaurant code: {code if code is not None else '—'}")

    def _rich_rider(self) -> InputRichBlockParagraph | None:
        f = self.facts
        if f.order_type != "delivery" or not (f.rider_name or f.rider_id):
            return None
        who = f.rider_name or f.rider_id or ""
        return InputRichBlockParagraph(text=f"🛵 Rider: {who}" + (f" — {f.rider_id}" if f.rider_name and f.rider_id else ""))

    def _rich_order(self, shown: int) -> list:
        """Items, money, pay line, notes, customer."""
        f = self.facts
        blocks: list = [InputRichBlockParagraph(text=RichTextBold(text="Items"))]
        for item in f.items[:shown]:
            lines = [f"• {_qty(item.qty)} × {item.name} — {_money(item.line_total)}"]
            lines += [f"   ↳ {m}" for m in item.mods]
            blocks.append(InputRichBlockParagraph(text="\n".join(lines)))
        if not f.items[:shown]:
            blocks.append(InputRichBlockParagraph(text="—"))
        if shown < len(f.items):
            blocks.append(InputRichBlockParagraph(text=f"… and {len(f.items) - shown} more items (see WhatsApp/printer)"))
        fee = f"Small order fee: {_money(f.small_order_fee)}\n" if f.small_order_fee else ""
        blocks.append(InputRichBlockParagraph(text=[fee, RichTextBold(text=f"Total: {_money(f.total)}")]))
        if f.pay_at_restaurant:
            blocks.append(InputRichBlockParagraph(text=RichTextBold(text=f"💷 Pay at restaurant — collect {_money(f.total)}")))
        if f.notes and f.notes.strip():
            note = f.notes.strip()
            note = note[:NOTES_LIMIT] + "…" if len(note) > NOTES_LIMIT else note
            blocks.append(InputRichBlockParagraph(text=[RichTextBold(text="📝 Notes"), "\n", RichTextItalic(text=note)]))
        if f.order_type == "delivery" and (f.customer_address or f.customer_phone):
            blocks.append(InputRichBlockParagraph(
                text="🏠 Customer: " + " — ".join(b for b in (f.customer_address, f.customer_phone) if b)
            ))
        return blocks

    def _rich(self, viewer: Viewer, shown: int) -> InputRichMessage:
        blocks = self._rich_head(viewer)
        rider = self._rich_rider()
        if self.phase == "handed_over":  # D55/D59: what happened on top, the order folded away
            blocks += self._flow_rows(self.timeline(viewer))
            if rider is not None:
                blocks.append(rider)
            blocks.append(InputRichBlockDetails(summary=ORDER_DETAILS, is_open=False, blocks=[
                self._rich_pickup(viewer), self._rich_code(), *self._rich_order(shown),
            ]))
        else:  # kitchen: the flow in the closed Progress block, everything the kitchen needs on top
            blocks.append(self._rich_pickup(viewer))
            if (progress := self._progress(viewer)) is not None:
                blocks.append(progress)
            blocks.append(self._rich_code())
            if rider is not None:
                blocks.append(rider)
            blocks += self._rich_order(shown)
        blocks += self._rich_actions()  # nothing after handover: _actions() offers no buttons then
        return InputRichMessage(blocks=blocks)

    def view(self, viewer: Viewer) -> View:
        if not viewer.authorised:
            return View(NO_ACCESS, None, True, rich=_note_rich(NO_ACCESS))
        if self.kind == "gone":
            return View(GONE_TEXT, None, True, rich=_note_rich(GONE_TEXT))
        text, shown = self._fit(viewer)
        try:
            rich = self._rich(viewer, shown)
        except Exception:  # the HTML form below is always enough to show the order
            logger.exception(f"receipt {self.facts.order_number}: rich form failed, HTML form only")
            rich = None
        return View(text, self._keyboard(viewer), self.kind in TERMINAL_KINDS, rich)


def _note_rich(text: str) -> InputRichMessage:
    """A one-line rich message. A copy that was sent as rich is also redrawn as rich when it turns into a notice,
    so the edit never has to turn a rich message into plain text."""
    return InputRichMessage(blocks=[InputRichBlockParagraph(text=text)])


def gone_view() -> View:
    """What every copy turns into when the order no longer exists."""
    return View(GONE_TEXT, None, True, rich=_note_rich(GONE_TEXT))


def receipt_toast(action: Literal["rdy", "adj"], order_type: OrderType, out: ActionOutcome) -> tuple[str, bool]:
    """(callback answer text, show_alert) for a Ready / +N tap."""
    r = out.result
    if r == "ok":
        if action == "rdy":
            who = "Rider" if order_type == "delivery" else "Customer"
            if out.follow_up_failed:
                return (f"Marked ready, but the {who.lower()} could not be messaged. Please contact them.", True)
            return f"Marked ready — {who.lower()} told", False
        return (f"Pickup {fmt_uk_time(out.pickup_time)}" if out.pickup_time else "Pickup time set"), False
    if r == "unchanged":
        return (f"Pickup already {fmt_uk_time(out.pickup_time)}" if out.pickup_time else "Pickup already set"), False
    if r == "already_ready":
        return (f"Already marked ready by {out.by_label}" if out.by_label else "Already marked ready"), False
    if r == "not_ready_state":
        if out.progress == "picked_up":
            return "Food already picked up", False
        return "This order is no longer in progress", False
    if r == "not_authorised":
        return NOT_ADMIN, True
    return GONE_TEXT, False
