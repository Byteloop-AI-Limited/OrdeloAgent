"""Removable /scratchpad playground for the restaurant-admin bot (aiogram 3.31.0).

Mount build_scratchpad_router() BEFORE the main rest_admin router in bots.py; remove
that include_router line to disable the command, callbacks and input handlers together.
Private-chat demos use dummy data and Bot API calls only: no order/payment/RPC calls.
ScratchpadInput holds only a pending contact/location request, never business state.
RichDemo keeps per-message demo controls in the dispatcher's temporary FSM storage;
/scratchpad or a restart clears those examples. No restaurant state is changed.
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
        await query.bot.send_message(query.message.chat.id, "This demo expired or that action isn't available. Open it again from /scratchpad.")
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
        await message.answer("Open /scratchpad in a private chat with this bot.")
        return
    await state.clear()
    await message.answer("Scratchpad keyboard cleared.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        "<b>Telegram scratchpad</b>\nChoose an example to try.\n"
        "All orders, contacts and addresses here are demo data.\n"
        "Send /scratchpad anytime to return to this menu.",
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


async def run_demo(query: CallbackQuery, demo: Demo, state: FSMContext) -> None:
    """One bounded demo per tap; progress cards advance by buttons, not long-running loops."""
    bot, chat_id = query.bot, query.message.chat.id
    action, value = demo.action, demo.value
    if action in RICH_DEMOS or action.startswith("rx_"):
        await run_rich_demo(query, demo, state)
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
        await bot.send_message(chat_id, "Scratchpad: try the keyboard below. /scratchpad cancels.",
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
        await bot.send_message(chat_id, "That scratchpad button is no longer available. Send /scratchpad.")


def build_scratchpad_router() -> Router:
    router = Router(name="rest_admin_scratchpad")
    router.message.register(show_menu, Command("scratchpad"))

    @router.callback_query(Demo.filter())
    async def on_demo(query: CallbackQuery, callback_data: Demo, state: FSMContext):
        if (not isinstance(query.message, Message) or query.message.chat.type != "private"
                or query.message.chat.id != query.from_user.id):
            await answer_quietly(query, "Use /scratchpad in your private chat with the bot.")
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
        await message.answer("Scratchpad received your location/contact. Send /scratchpad to try another example.", reply_markup=ReplyKeyboardRemove())

    return router
