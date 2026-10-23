"""Removable /eg playground for the restaurant-admin bot (aiogram 3.31.0).

Mount build_scratchpad_router() BEFORE the main rest_admin router in bots.py; remove
that include_router line to disable the command, callbacks and input handlers together.
Private-chat demos use dummy data and Bot API calls only: no order/payment/RPC calls.
ScratchpadInput holds only a pending contact/location request, never business state.
RichDemo keeps per-message demo controls in the dispatcher's temporary FSM storage; SeenDemo does
the same for the four "latest status since you last looked" examples (Telegram sends bots no read
receipts, so "seen" there means the admin tapped something). /eg or a restart clears those
examples. No restaurant state is changed.
Notebook companion: notebooks/telegram/tgram_scratchpad.py.
"""

import asyncio
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.methods import SendMessage
from aiogram.types import (
    BufferedInputFile, CallbackQuery, DisabledButton, InlineKeyboardButton, InlineKeyboardMarkup,
    InputRichBlockButtons, InputRichBlockDetails, InputRichBlockParagraph,
    InputRichBlockSectionHeading, InputRichBlockTable, InputRichMessage, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, ReplyParameters, RichMessageButton,
    RichBlockTableCell, RichTextButton, RichTextDateTime, WebAppInfo,
)

from ..replies import answer_quietly


class Demo(CallbackData, prefix="scratch"):
    action: str
    value: int = 0


class ScratchpadInput(StatesGroup):
    waiting = State()


DEMOS = (
    ("🌐 Salisbury Mini App", "mini_app"),
    ("🧾 Expandable receipt", "receipt"), ("🎨 Coloured actions", "colours"),
    ("🟠 Show progress", "progress"), ("⏱ Pickup: prep presets", "pickup_slots"),
    ("➕ Pickup: adjust time", "pickup_eta"), ("🍽 Pickup: ready / hold", "pickup_ready"),
    ("🆕 Since last seen", "seen_log"), ("🚦 Status badge + flow", "seen_badge"),
    ("🔔 Rolling nudge", "seen_nudge"), ("⬇️ Re-post latest", "seen_bump"),
    ("🧾 Receipt phases", "rcpt_phases"), ("🧪 Rows in details", "rcpt_probe"),
    ("📝 Text & formatting", "text"), ("↩️ Reply", "reply"),
    ("✏️ Edit a message", "edit"), ("🗑 Delete a message", "delete"),
    ("⏳ Draft preview", "draft"), ("🛵 Delivery tracker", "tracker"),
    ("🧾 Restaurant order card", "card"), ("🔘 Inline keyboard", "keyboard"),
    ("✨ Buttons inside text", "rich"), ("📍 Request location", "ask_location"),
    ("👤 Request contact", "ask_contact"), ("⌨️ Remove keyboard", "remove"),
    ("🗺 Map pin", "location"), ("🏛 Venue", "venue"),
    ("☎️ Demo contact", "contact"), ("🎲 Dice", "dice"),
    ("📎 CSV document", "file"), ("🎉 Message effect", "effect"),
    ("⚠️ Error handling", "error"), ("🤖 Bot info", "info"),
)
STEPS = ("🧾 Order received", "👨‍🍳 Preparing", "🛵 Rider picked up", "📍 Nearby", "✅ Delivered")
CARD_STATUS = ("New order", "Preparing", "Ready", "Picked up", "Delivered", "Declined")
RICH_DEMOS = {"receipt", "colours", "progress", "pickup_slots", "pickup_eta", "pickup_ready"}
DEMO_NOTE = "Demo only · these controls do not change a real order or contact a rider."
SEEN_DEMOS = {"seen_log", "seen_badge", "seen_nudge", "seen_bump"}
SEEN_UPDATES = (
    "🔔 New order — accept or decline",
    "🔔 Reminder 2 of 4 — nobody has answered",
    "✅ Accepted by Ada — waiting for pickup time",
    "⏰ Pickup time set by Ada",
    "🍽 Food ready for the rider",
)
SEEN_STYLES = ("primary", "primary", "success", "success", "success")
SEEN_GAP = 180  # demo updates are three minutes apart, so the relative times differ
SEEN_NOTE = "Demo only · Next update pretends the system edited this card while you were away."


@dataclass(frozen=True)
class RichDemo:
    kind: str
    pickup_at: int
    minutes: int = 20
    confirmed: bool = False
    ready: bool = False
    decision: int = 0
    completed: int = 2
    expanded: bool = False


@dataclass(frozen=True)
class SeenDemo:
    """State of one "since you last looked" example message.

    `n` updates have happened and the admin has acknowledged the first `seen` of them. Telegram
    gives bots no read receipts or view counts, so acknowledging means tapping: Mark seen, the
    badge, the nudge's Seen button, or (on a real card) any button.
    """

    kind: str
    base: int  # unix time of update 0; update i happened at base + i * SEEN_GAP
    n: int = 1
    seen: int = 1
    nudge_id: int = 0  # seen_nudge only: message id of the one live nudge, 0 for none
    expanded: bool = False  # seen_badge only: is the step flow open

    @property
    def unseen(self) -> int:
        return self.n - self.seen

    def at(self, index: int) -> int:
        return self.base + index * SEEN_GAP


def rich_action(text: str, action: str | None = None, value: int = 0,
                style: str | None = None) -> RichMessageButton:
    """Omitting an action makes a genuinely disabled button, with no callback data."""
    return RichMessageButton(
        text=text, style=style,
        **({"callback_data": Demo(action=action, value=value).pack()}
           if action else {"disabled": DisabledButton()}),
    )


def receipt_message() -> InputRichMessage:
    rows = [
        ("Qty", "Item", "Line total"), ("1", "Vegetable Biryani", "£12.56"),
        ("1", "Mango Lassi", "£2.70"), ("2", "Garlic Naan", "£6.40"),
        ("1", "Paneer Tikka", "£7.95"), ("1", "Onion Bhaji", "£4.50"),
        ("1", "Raita", "£1.95"),
    ]
    return InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="Kitchen receipt · Demo #1042", size=3),
        InputRichBlockParagraph(text="Delivery · 7 items · £36.06 · Preparing"),
        InputRichBlockDetails(summary="View items and kitchen notes", is_open=False, blocks=[
            InputRichBlockTable(is_bordered=True, is_striped=True, cells=[
                [RichBlockTableCell(text=cell, align="right" if col == 2 else "left",
                                    valign="middle", is_header=row == 0)
                 for col, cell in enumerate(cells)] for row, cells in enumerate(rows)
            ]),
            InputRichBlockParagraph(text="Kitchen note: pack the lassi separately. Demo note only."),
        ]),
        InputRichBlockDetails(summary="View rider and handover details", is_open=False, blocks=[
            InputRichBlockParagraph(text="Demo Rider · +447700900123\nHandover code: 39\n1 Demo Street, Salisbury SP1 3TA"),
        ]),
        InputRichBlockParagraph(text=DEMO_NOTE),
    ])


def coloured_actions_message(decision: int) -> InputRichMessage:
    decided = decision != 0
    return InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="Demo #1042 · Coloured actions", size=3),
        InputRichBlockParagraph(text=("Awaiting decision", "✅ Accepted", "❌ Declined")[decision]),
        InputRichBlockButtons(buttons=[
            rich_action("✅ Accepted" if decision == 1 else "Accept", None if decided else "rx_decide", 1, "success"),
            rich_action("❌ Declined" if decision == 2 else "Decline", None if decided else "rx_decide", 2, "danger"),
            rich_action("Reset demo", "rx_reset", style="primary"),
        ]),
        InputRichBlockParagraph(text="Green accepts, red declines, blue restarts. Once decided, both decision buttons are disabled."),
        InputRichBlockParagraph(text=DEMO_NOTE),
    ])


def progress_message(completed: int, expanded: bool) -> InputRichMessage:
    blocks = [
        InputRichBlockSectionHeading(text="Demo #1042 · Order progress", size=3),
        InputRichBlockParagraph(text=[
            "Rider: Demo Rider · ",
            RichTextButton(button=rich_action("Hide progress" if expanded else "Show progress",
                                             "rx_expand", int(not expanded), "primary")),
        ]),
    ]
    if expanded:
        labels = ("Order Accepted", "Rider Assigned", "Food pickup", "Delivery complete")
        for index, label in enumerate(labels):
            if index < completed:
                button = rich_action(f"✅ {label}", style="success")
            elif index == completed:
                # Bot API has no orange style: use an orange marker + the supported blue style.
                button = rich_action(f"🟠 {label} · next", "rx_next", index + 1, "primary")
            else:
                button = rich_action(f"🔒 {label} · pending")
            blocks.append(InputRichBlockButtons(buttons=[button]))
        blocks.append(InputRichBlockParagraph(text="Completed steps are green and disabled. Tap the next step to simulate it; later steps stay disabled."))
        blocks.append(InputRichBlockButtons(buttons=[rich_action("Reset demo", "rx_reset", style="primary")]))
    blocks.append(InputRichBlockParagraph(text=DEMO_NOTE))
    return InputRichMessage(blocks=blocks)


def pickup_message(demo: RichDemo) -> InputRichMessage:
    locked = demo.confirmed or demo.ready
    when = RichTextDateTime(text="pickup time", unix_time=demo.pickup_at, date_time_format="t")
    blocks = [InputRichBlockSectionHeading(text="Demo #1042 · Embedded pickup controls", size=3)]
    if demo.kind == "pickup_slots":
        blocks.append(InputRichBlockParagraph(text=["Ready in ", *[
            part for minutes in (10, 20, 30)
            for part in (RichTextButton(button=rich_action(
                f"{'✓ ' if minutes == demo.minutes else ''}{minutes} min",
                None if locked else "rx_slot", minutes,
                "success" if minutes == demo.minutes else "primary",
            )), " ")
        ], "· pickup at ", when]))
    elif demo.kind == "pickup_eta":
        blocks.append(InputRichBlockParagraph(text=[
            "Pickup at ", when, " · ",
            *[part for delta in (-5, 5, 10) for part in (
                RichTextButton(button=rich_action(f"{delta:+} min", None if locked else "rx_delay", delta, "primary")), " ",
            )],
        ]))
    else:
        blocks.append(InputRichBlockParagraph(text=[
            "Kitchen: ", RichTextButton(button=rich_action("✅ Food ready" if demo.ready else "Preparing",
                                                            style="success" if demo.ready else None)),
            " · pickup at ", when, ". ",
            RichTextButton(button=rich_action("Mark food ready", None if locked else "rx_ready", style="success")),
            " or hold for ",
            RichTextButton(button=rich_action("+10 min", None if locked else "rx_delay", 10, "primary")), " ",
            RichTextButton(button=rich_action("+20 min", None if locked else "rx_delay", 20, "primary")),
        ]))
    if demo.kind != "pickup_ready":
        blocks.append(InputRichBlockParagraph(text=[
            RichTextButton(button=rich_action("✅ Pickup time confirmed" if locked else "Confirm pickup time",
                                             None if locked else "rx_confirm", style="success")),
            " ", RichTextButton(button=rich_action("Edit time" if locked else "Reset demo",
                                                   "rx_edit" if locked else "rx_reset", style="primary")),
        ]))
    elif demo.ready:
        blocks.append(InputRichBlockParagraph(text=[RichTextButton(button=rich_action("Restart demo", "rx_reset", style="primary"))]))
    blocks.append(InputRichBlockParagraph(text=DEMO_NOTE))
    return InputRichMessage(blocks=blocks)


def render_rich_demo(demo: RichDemo) -> InputRichMessage:
    if demo.kind == "receipt":
        return receipt_message()
    if demo.kind == "colours":
        return coloured_actions_message(demo.decision)
    if demo.kind == "progress":
        return progress_message(demo.completed, demo.expanded)
    return pickup_message(demo)


def advance_rich_demo(current: RichDemo, action: str, value: int) -> RichDemo | None:
    """Only the current demo's actions apply; stale completed controls cannot undo progress."""
    if action == "rx_reset":
        return RichDemo(kind=current.kind, pickup_at=int(time.time()) + 20 * 60)
    if current.kind == "colours" and action == "rx_decide" and value in (1, 2):
        return current if current.decision else replace(current, decision=value)
    if current.kind == "progress":
        if action == "rx_expand" and value in (0, 1):
            return replace(current, expanded=bool(value))
        if action == "rx_next" and 3 <= value <= min(4, current.completed + 1):
            return replace(current, completed=max(current.completed, value), expanded=True)
    if current.kind.startswith("pickup_"):
        if current.confirmed or current.ready:
            if action == "rx_edit" and current.kind != "pickup_ready":
                return replace(current, confirmed=False)
            return current  # queued taps on controls that are now disabled have no effect
        if action == "rx_slot" and current.kind == "pickup_slots" and value in (10, 20, 30):
            return replace(current, minutes=value, pickup_at=int(time.time()) + value * 60)
        if action == "rx_delay" and ((current.kind == "pickup_eta" and value in (-5, 5, 10))
                                     or (current.kind == "pickup_ready" and value in (10, 20))):
            return replace(current, pickup_at=max(int(time.time()) + 5 * 60, current.pickup_at + value * 60))
        if action == "rx_confirm" and current.kind in ("pickup_slots", "pickup_eta"):
            return replace(current, confirmed=True)
        if action == "rx_ready" and current.kind == "pickup_ready":
            return replace(current, ready=True)
    return None


async def run_rich_demo(query: CallbackQuery, demo: Demo, state: FSMContext) -> None:
    if demo.action in RICH_DEMOS:
        current = RichDemo(kind=demo.action, pickup_at=int(time.time()) + 20 * 60)
        message = await query.bot.send_rich_message(query.message.chat.id, rich_message=render_rich_demo(current))
        await state.update_data({f"scratchpad:{message.message_id}": asdict(current)})
        return
    key = f"scratchpad:{query.message.message_id}"
    saved = (await state.get_data()).get(key)
    updated = advance_rich_demo(RichDemo(**saved), demo.action, demo.value) if saved else None
    if updated is None:
        await query.bot.send_message(query.message.chat.id, "This demo expired or that action isn't available. Open it again from /eg.")
        return
    await state.update_data({key: asdict(updated)})
    await edit_demo(query, rich_message=render_rich_demo(updated))


def buttons(*rows: list[tuple[str, str, int]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=Demo(action=action, value=value).pack())
         for label, action, value in row] for row in rows
    ])


def menu_keyboard() -> InlineKeyboardMarkup:
    entries = [(label, action, 0) for label, action in DEMOS]
    return buttons(*(entries[i:i + 2] for i in range(0, len(entries), 2)))


async def show_menu(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("Open /eg in a private chat with this bot.")
        return
    await state.clear()
    await message.answer("Scratchpad keyboard cleared.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "<b>Telegram scratchpad</b>\nChoose an example to try.\n"
        "All orders, contacts and addresses here are demo data.\n"
        "Send /eg anytime to return to this menu.",
        parse_mode="HTML", reply_markup=menu_keyboard(),
    )


def rich_button_message(ready: bool = False) -> InputRichMessage:
    """A button embedded between words, rather than a keyboard under the message."""
    return InputRichMessage(blocks=[InputRichBlockParagraph(text=[
        "Demo order #1042 is ",
        RichTextButton(button=RichMessageButton(
            text="✅ Ready" if ready else "👨‍🍳 Preparing",
            style="success" if ready else "primary",
            callback_data=Demo(action="rich_toggle", value=0 if ready else 1).pack(),
        )),
        ". Tap the status to change it; the same message is edited in place.",
    ])])


def tracker(step: int) -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"<s>{label}</s>" for label in STEPS[:step]] + [f"<b>{STEPS[step]}</b>"]
    if step < 4:
        eta = int(time.time()) + 8 * 60
        lines.append(f'\nArriving <tg-time unix="{eta}" format="r">in ~8 minutes</tg-time>')
    return "<b>Demo delivery #1042</b>\n\n" + "\n".join(lines), buttons(
        [("Restart" if step == 4 else "Next step →", "tracker_step", 0 if step == 4 else step + 1)],
    )


def order_card(step: int, minutes: int = 10) -> tuple[str, InlineKeyboardMarkup]:
    pickup = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    text = (
        f"<b>Demo order #1042 · Kitchen</b>\nStatus: <b>{CARD_STATUS[step]}</b>\n\n"
        "<blockquote expandable><b>Items (6)</b>\n"
        "• 1 × Vegetable Biryani — £12.56\n• 1 × Mango Lassi — £2.70\n"
        "• 2 × Garlic Naan — £6.40\n• 1 × Paneer Tikka — £7.95\n"
        "• 1 × Onion Bhaji — £4.50\n• 1 × Raita — £1.95</blockquote>\n"
        "<b>Total: £36.06</b>\n\n"
        f'⏰ Pickup <tg-time unix="{int(pickup.timestamp())}" format="t">in {minutes} min</tg-time>\n'
        "🛵 Demo Rider · +447700900123\n🔢 Code: <tg-spoiler>39</tg-spoiler>\n"
        "🏠 1 Demo Street, Salisbury SP1 3TA\n\n"
        "<i>Demo only: buttons update this card; no restaurant, rider or payment is affected.</i>"
    )
    if step == 0:
        kb = buttons([("✅ Accept", "card_step", 1), ("❌ Decline", "card_step", 5)])
    elif step == 1:
        kb = buttons([("🔔 Ready", "card_step", 2)],
                     [("Pickup +10m", "card_time", 10), ("Pickup +20m", "card_time", 20)])
    elif step in (2, 3):
        kb = buttons([("🛵 Picked up" if step == 2 else "✅ Delivered", "card_step", step + 1)])
    else:
        kb = buttons([("Restart demo", "card_step", 0)])
    return text, kb


async def edit_demo(query: CallbackQuery, **content) -> None:
    try:
        await query.bot.edit_message_text(
            chat_id=query.message.chat.id, message_id=query.message.message_id, **content,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise


def seen_key(message_id: int) -> str:
    return f"scratchpad_seen:{message_id}"


def new_seen_demo(kind: str) -> SeenDemo:
    """The admin has just looked at the first update; the last one will be 'now'."""
    base = int(time.time()) - (len(SEEN_UPDATES) - 1) * SEEN_GAP
    if kind == "seen_badge":  # opens mid-flow with two unseen updates: something to see before any tap
        return SeenDemo(kind=kind, base=base, n=3, seen=1, expanded=True)
    return SeenDemo(kind=kind, base=base)


def seen_time(unix: int) -> str:
    """Relative time ("5 minutes ago") that Telegram clients keep current without any edit."""
    return f'<tg-time unix="{unix}" format="r">earlier</tg-time>'


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def seen_card(demo: SeenDemo) -> tuple[str, InlineKeyboardMarkup]:
    """HTML card for seen_log (full change log), seen_nudge and seen_bump (was -> now)."""
    latest = SEEN_UPDATES[demo.n - 1]
    mark = "🆕 " if demo.unseen else ""
    banner = (f"🆕 <b>{plural(demo.unseen, 'update')} since you last looked</b>" if demo.unseen
              else "✓ <b>You're up to date</b>")
    when = seen_time(demo.at(demo.n - 1))
    if demo.kind == "seen_bump":
        # A re-posted card is a new message, so its first line is the lock-screen preview: status first.
        lines = [f"{mark}<b>{latest}</b>", f"Demo order #1042 · Kitchen · updated {when}", banner]
    else:
        lines = ["<b>Demo order #1042 · Kitchen</b>", banner, "", f"{mark}<b>{latest}</b>", f"updated {when}"]
    if demo.kind == "seen_log" and demo.n > 1:
        # tg-time stays outside <b>/<i>: Telegram does not guarantee entity nesting for it.
        earlier = [
            f"🆕 <b>{SEEN_UPDATES[i]}</b> · {seen_time(demo.at(i))}" if i >= demo.seen
            else f"<i>{SEEN_UPDATES[i]}</i> · {seen_time(demo.at(i))}"
            for i in reversed(range(demo.n - 1))
        ]
        lines += ["", "\n".join(["<blockquote expandable><b>Earlier</b>", *earlier]) + "</blockquote>"]
    elif demo.kind != "seen_log" and demo.unseen:
        lines += ["", f"Was: <i>{SEEN_UPDATES[demo.seen - 1]}</i>"]
    lines += ["", f"<i>{SEEN_NOTE}</i>"]
    row = [("👁 Mark seen", "sn_seen", 0)] if demo.unseen else []
    row.append(("Next update →", "sn_next", 0) if demo.n < len(SEEN_UPDATES) else ("Restart", "sn_reset", 0))
    return "\n".join(lines), buttons(row)


def seen_step_button(demo: SeenDemo, index: int) -> RichMessageButton:
    """One stage of the flow. Colour = newer than you have looked at; grey = quiet; lock = still to come."""
    label = SEEN_UPDATES[index]
    if index >= demo.n:
        return rich_action(f"🔒 {label} · pending")
    if index == demo.n - 1:  # the current stage: tappable (marks seen) while unread
        if demo.unseen:
            return rich_action(f"🆕 {label}", "sn_seen", style=SEEN_STYLES[index])
        return rich_action(f"● {label}")
    if index >= demo.seen:  # passed while you were away: completed, but new to you
        return rich_action(f"🆕 {label}", style="success")
    return rich_action(f"✓ {label}")


def seen_badge_message(demo: SeenDemo) -> InputRichMessage:
    """One glanceable message: a status badge, plus a collapsible visual flow of every stage."""
    latest = SEEN_UPDATES[demo.n - 1]
    badge = (rich_action(f"🆕 {latest}", "sn_seen", style=SEEN_STYLES[demo.n - 1]) if demo.unseen
             else rich_action(f"✓ {latest}"))
    when = RichTextDateTime(text="earlier", unix_time=demo.at(demo.n - 1), date_time_format="r")
    blocks = [
        InputRichBlockSectionHeading(text="Demo order #1042 · Latest status", size=3),
        InputRichBlockButtons(buttons=[badge]),
        InputRichBlockParagraph(text=[
            "Updated ", when,
            f" · {plural(demo.unseen, 'update')} since you last looked (tap the badge to mark seen). "
            if demo.unseen else " · you've seen this. ",
            RichTextButton(button=rich_action("Hide steps" if demo.expanded else "Show steps",
                                             "sn_toggle", int(not demo.expanded))),
        ]),
    ]
    if demo.expanded:
        blocks += [InputRichBlockButtons(buttons=[seen_step_button(demo, i)]) for i in range(len(SEEN_UPDATES))]
    more = demo.n < len(SEEN_UPDATES)
    blocks.append(InputRichBlockParagraph(text=[
        RichTextButton(button=rich_action("Next update →" if more else "Restart demo",
                                         "sn_next" if more else "sn_reset")),
        " pretends the system edited this message while you were away.",
    ]))
    blocks.append(InputRichBlockParagraph(text=DEMO_NOTE))
    return InputRichMessage(blocks=blocks)


RECEIPT_PHASES = ("open@13:00", "ready@13:00", "picked_up", "done", "rider_cancelled")


def demo_receipt(index: int) -> InputRichMessage:
    """The REAL Receipt.view() for a fake delivery in each state, plus a 'Next state' control (a Demo callback).

    Stateless: the state index is in the callback data. The receipt's own Ready / +N / badge buttons carry real
    OrderAction data for the fake order DEMO-PHASE-1; the orders router answers them with 'no longer available'."""
    from .order_cards.model import Viewer
    from .receipts.model import Receipt, ReceiptSnapshot

    now = datetime.now(timezone.utc).replace(microsecond=0)

    def iso(minutes: int) -> str:
        return (now + timedelta(minutes=minutes)).isoformat()

    index %= len(RECEIPT_PHASES)
    status = RECEIPT_PHASES[index]
    ada = {"label": "Ada", "phone": "447700900001"}
    ready = status != "open@13:00"
    facts = {
        "order_number": "DEMO-PHASE-1", "order_type": "delivery", "rest_name": "Demo", "rest_code": 47,
        "pickup_at": iso(10), "pickup_initial": iso(0), "pickup_adjusted_by": ada,
        "ready_at": iso(-2) if ready else None, "ready_by": ada if ready else None,
        "rider": {"id": "447700900123", "name": "Demo Rider"},
        "customer": {"address": "1 Demo Street, Salisbury SP1 3TA", "phone": "447700900999"},
        "items": [{"qty": 2, "name": "Chicken Shawarma", "line_total": 17.0, "mods": ["extra garlic sauce"]},
                  {"qty": 1, "name": "Fries", "line_total": 3.5, "mods": []}],
        "small_order_fee": 1.0, "total": 21.5, "notes": "Please ring the bell twice (demo)", "pay_at_restaurant": False,
        "completed_at": iso(25) if status == "done" else None,
        "accepted_by": ada, "accepted_at": iso(-20), "accepted_auto": False,
    }
    snap = ReceiptSnapshot.from_json({"status": status, "rest_ref": "DEMO", "dispatch_id": 1, "facts": facts})
    rich = Receipt.from_snapshot(snap).view(Viewer("447700900002")).rich
    nav = InputRichBlockButtons(buttons=[rich_action(f"Next state → (now: {status.partition('@')[0]})", "rp_next", index + 1, "primary")])
    return InputRichMessage(blocks=[*rich.blocks, nav, InputRichBlockParagraph(text=DEMO_NOTE)])


def nested_rows_probe() -> InputRichMessage:
    """Spike: button rows inside a closed details block, plus the three disabled styles side by side."""
    def row(text: str, style: str | None = None) -> InputRichBlockButtons:
        return InputRichBlockButtons(buttons=[rich_action(text, style=style)])

    return InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="Spike · rows inside details", size=3),
        InputRichBlockDetails(summary="Progress · step 3 of 5", is_open=False, blocks=[
            row("✓ ✅ Accepted by Ada · 9:02 AM"), row("✓ ⏰ Pickup 9:41 AM"), row("● 🍳 Ready by Ada · 9:35 AM", "success"),
            row("🔒 🛵 Rider picks up · pending"), row("🔒 🏁 Delivered · pending"),
        ]),
        row("disabled · default style"), row("disabled · success", "success"), row("disabled · danger", "danger"),
        InputRichBlockParagraph(text=DEMO_NOTE),
    ])


def seen_content(demo: SeenDemo) -> dict:
    """Keyword arguments shared by send and edit for whichever kind of message the demo is."""
    if demo.kind == "seen_badge":
        return {"rich_message": seen_badge_message(demo)}
    text, keyboard = seen_card(demo)
    return {"text": text, "parse_mode": "HTML", "reply_markup": keyboard}


async def send_seen(bot, chat_id: int, demo: SeenDemo) -> Message:
    content = seen_content(demo)
    if demo.kind == "seen_badge":
        return await bot.send_rich_message(chat_id, rich_message=content["rich_message"])
    return await bot.send_message(chat_id, **content)


async def delete_quietly(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass  # already deleted by the admin


def advance_seen_demo(current: SeenDemo, action: str, value: int = 0) -> SeenDemo | None:
    """Only the actions a message currently offers apply; a queued stale tap is refused."""
    if action == "sn_reset":
        return replace(new_seen_demo(current.kind), nudge_id=current.nudge_id)
    if action == "sn_next" and current.n < len(SEEN_UPDATES):
        return replace(current, n=current.n + 1)
    if action in ("sn_seen", "sn_nudge_seen"):
        return replace(current, seen=current.n)
    if action == "sn_toggle" and value in (0, 1):
        return replace(current, expanded=bool(value))
    return None


async def run_seen_demo(query: CallbackQuery, demo: Demo, state: FSMContext) -> None:
    bot, chat_id = query.bot, query.message.chat.id
    if demo.action in SEEN_DEMOS:
        current = new_seen_demo(demo.action)
        message = await send_seen(bot, chat_id, current)
        await state.update_data({seen_key(message.message_id): asdict(current)})
        return
    # Only the nudge's Seen button carries a card id (it lives in a different message than its card).
    card_id = demo.value if demo.action == "sn_nudge_seen" else query.message.message_id
    key = seen_key(card_id)
    saved = (await state.get_data()).get(key)
    current = SeenDemo(**saved) if saved else None
    updated = advance_seen_demo(current, demo.action, demo.value) if current else None
    if updated is None:
        await bot.send_message(chat_id, "This demo expired or that action isn't available. Open it again from /eg.")
        return
    if updated.kind == "seen_nudge":
        # Edits are silent, so a change also sends ONE notifying reply under the card. Its first line
        # is the status because that line is the lock-screen preview. A newer change, Mark seen or
        # Restart removes the older nudge, so at most one is ever live.
        if demo.action == "sn_next":
            nudge = await bot.send_message(
                chat_id, f"<b>{SEEN_UPDATES[updated.n - 1]}</b>\nOrder #1042 · tap Seen once you've looked",
                parse_mode="HTML",
                reply_parameters=ReplyParameters(message_id=card_id, allow_sending_without_reply=True),
                reply_markup=buttons([("👁 Seen", "sn_nudge_seen", card_id)]),
            )
            updated = replace(updated, nudge_id=nudge.message_id)
        else:
            updated = replace(updated, nudge_id=0)
        if current.nudge_id:
            await delete_quietly(bot, chat_id, current.nudge_id)
    if updated.kind == "seen_bump" and demo.action == "sn_next":
        # Edits never move a message or notify. Re-posting does both; the state follows the new id.
        message = await send_seen(bot, chat_id, updated)
        data = await state.get_data()
        data.pop(key, None)
        data[seen_key(message.message_id)] = asdict(updated)
        await state.set_data(data)
        await delete_quietly(bot, chat_id, card_id)
        return
    await state.update_data({key: asdict(updated)})
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=card_id, **seen_content(updated))
    except TelegramBadRequest as exc:
        if "message is not modified" not in exc.message.lower():
            raise


async def run_demo(query: CallbackQuery, demo: Demo, state: FSMContext) -> None:
    """One bounded demo per tap; progress cards advance by buttons, not long-running loops."""
    bot, chat_id = query.bot, query.message.chat.id
    action, value = demo.action, demo.value
    if action in RICH_DEMOS or action.startswith("rx_"):
        await run_rich_demo(query, demo, state)
    elif action in SEEN_DEMOS or action.startswith("sn_"):
        await run_seen_demo(query, demo, state)
    elif action == "rcpt_probe":
        await bot.send_rich_message(chat_id, rich_message=nested_rows_probe())
    elif action == "rcpt_phases":
        await bot.send_rich_message(chat_id, rich_message=demo_receipt(0))
    elif action == "rp_next":
        await edit_demo(query, rich_message=demo_receipt(value))
    elif action == "mini_app":
        await bot.send_message(
            chat_id, "Browse Salisbury restaurants inside Telegram (live storefront).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="Open Salisbury", style="primary",
                    web_app=WebAppInfo(url="https://restaurant.ordelo.app/town/salisbury"),
                ),
            ]]),
        )
    elif action == "text":
        await bot.send_message(chat_id, "Hello from the scratchpad 👋\n<b>bold</b> <i>italic</i> <code>code</code>", parse_mode="HTML")
    elif action == "reply":
        await bot.send_message(chat_id, "This replies to the scratchpad menu.", reply_parameters=ReplyParameters(message_id=query.message.message_id))
    elif action == "edit":
        await bot.send_message(chat_id, "Original demo text. Tap Edit below.", reply_markup=buttons([("✏️ Edit", "edit_now", 0)]))
    elif action == "edit_now":
        await edit_demo(query, text="<b>Edited in place.</b> The message id stayed the same.", parse_mode="HTML", reply_markup=None)
    elif action == "delete":
        await bot.send_message(chat_id, "Tap below to delete this demo message.", reply_markup=buttons([("🗑 Delete me", "delete_now", 0)]))
    elif action == "delete_now":
        await bot.delete_message(chat_id, query.message.message_id)
    elif action == "draft":
        draft_id = query.message.message_id
        for text in ("Thinking…", "Demo order #1042", "Demo order #1042 is ready for pickup."):
            await bot.send_message_draft(chat_id=chat_id, draft_id=draft_id, text=text)
            await asyncio.sleep(0.4)
        await bot.send_message(chat_id, "Demo order #1042 is ready for pickup.")
    elif action in ("tracker", "tracker_step") and 0 <= value < len(STEPS):
        text, kb = tracker(value)
        if action == "tracker":
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        else:
            await edit_demo(query, text=text, parse_mode="HTML", reply_markup=kb)
    elif (action in ("card", "card_step") and 0 <= value < len(CARD_STATUS)) or (action == "card_time" and value in (10, 20)):
        text, kb = order_card(1, value) if action == "card_time" else order_card(value)
        if action == "card":
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)
        else:
            await edit_demo(query, text=text, parse_mode="HTML", reply_markup=kb)
    elif action == "keyboard":
        kb = buttons([("Ping", "ping", 0)])
        kb.inline_keyboard.insert(0, [InlineKeyboardButton(text="Docs", url="https://core.telegram.org/bots/api")])
        await bot.send_message(chat_id, "Custom inline keyboard", reply_markup=kb)
    elif action == "ping":
        await edit_demo(query, text="Pong! Tap again to change the button.", reply_markup=buttons([("Ping again", "ping", 0)]))
    elif action == "rich":
        await bot.send_rich_message(chat_id, rich_message=rich_button_message())
    elif action == "rich_toggle" and value in (0, 1):
        await edit_demo(query, rich_message=rich_button_message(bool(value)))
    elif action in ("ask_location", "ask_contact"):
        location = action == "ask_location"
        key = KeyboardButton(text="📍 Share location", request_location=True) if location else KeyboardButton(text="👤 Share my contact", request_contact=True)
        await state.set_state(ScratchpadInput.waiting)
        await bot.send_message(chat_id, "Scratchpad: try the keyboard below. /eg cancels.",
                               reply_markup=ReplyKeyboardMarkup(keyboard=[[key]], resize_keyboard=True, one_time_keyboard=True))
    elif action == "remove":
        await state.clear()
        await bot.send_message(chat_id, "Scratchpad keyboard removed.", reply_markup=ReplyKeyboardRemove())
    elif action == "location":
        await bot.send_location(chat_id, latitude=51.5014, longitude=-0.1419)
    elif action == "venue":
        await bot.send_venue(chat_id, latitude=51.5014, longitude=-0.1419, title="Buckingham Palace", address="London SW1A 1AA")
    elif action == "contact":
        await bot.send_contact(chat_id, phone_number="+447700900123", first_name="Demo", last_name="Rider")
    elif action == "dice":
        await bot.send_dice(chat_id, emoji="🎲")
    elif action == "file":
        await bot.send_document(chat_id, BufferedInputFile(b"id,name\n1,demo\n", "demo.csv"), caption="A scratchpad CSV")
    elif action == "effect":
        await bot.send_message(chat_id, "Demo delivery complete 🎉", message_effect_id="5046509860389126442")
    elif action == "error":
        # Exercise the exception handler locally, without messaging an unrelated chat.
        try:
            raise TelegramBadRequest(method=SendMessage(chat_id=chat_id, text="demo"), message="Simulated invalid request")
        except TelegramBadRequest:
            await bot.send_message(chat_id, "Caught a simulated TelegramBadRequest. A handler can explain an error here.")
    elif action == "info":
        me = await bot.get_me()
        await bot.send_message(chat_id, f"Bot: @{me.username}\nBot id: {me.id}\nYour private chat id: {chat_id}")
    else:
        await bot.send_message(chat_id, "That scratchpad button is no longer available. Send /eg.")


def build_scratchpad_router() -> Router:
    router = Router(name="rest_admin_scratchpad")
    router.message.register(show_menu, Command("eg", "scratchpad"))  # /scratchpad kept as an alias

    @router.callback_query(Demo.filter())
    async def on_demo(query: CallbackQuery, callback_data: Demo, state: FSMContext):
        if (not isinstance(query.message, Message) or query.message.chat.type != "private"
                or query.message.chat.id != query.from_user.id):
            await answer_quietly(query, "Use /eg in your private chat with the bot.")
            return
        answered = asyncio.create_task(answer_quietly(query))
        try:
            await run_demo(query, callback_data, state)
        except TelegramBadRequest:
            await query.bot.send_message(query.message.chat.id, "Telegram couldn't display this example here. Try another demo or update your Telegram app.")
        finally:
            await answered

    @router.message(ScratchpadInput.waiting, F.chat.type == "private", F.location | F.contact)
    async def received_input(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Scratchpad received your location/contact. Send /eg to try another example.", reply_markup=ReplyKeyboardRemove())

    return router
