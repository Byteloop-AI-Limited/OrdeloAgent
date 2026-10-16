# %% [markdown]
# # Telegram bot scratchpad (restaurant-admin bot)
# Run cell by cell (VS Code "Run Cell", Jupyter, or `ipython`). Cells use top-level `await`.
# Run from the repo root with the main project .venv, PYTHONPATH="$PWD" and AWS_SETTINGS_* set
# (see docs/local-testing-runbook.md section 1): importing `config` loads every OrdeloAgent setting.
#
# Rules of thumb:
# - Sending to a chat only works after that person pressed Start on the bot (or you did).
# - Webhook registration lives in tgram_setup_bot.py. This notebook only sends and inspects.
# - This talks to the REAL Bot API. Anything you send is really sent.
# - The dev bot is shared with tgram_starter; see tgram_setup_bot.py before changing its webhook.
# - Interactive versions of these demos: send /scratchpad to the main restaurant-admin bot.
#   Router: channels/telegram/rest_admin/scratchpad.py (mounted in channels/telegram/bots.py).

# %% 1. Setup: imports, settings, bot
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "channels" / "telegram").is_dir())
sys.path.insert(0, str(ROOT))

from aiogram.types import (  # noqa: E402
    BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,  # noqa: F401 (used in commented cell)
)

from config import rest_admin_bot as bot, tgram_rest_admin_settings as settings  # noqa: E402

print("bot_key:", settings.bot_key, "| username:", settings.bot_username, "| webhook:", settings.webhook_url or "(base url not set)")

# %% 2. Who am I? (validates the token)
me = await bot.get_me()
print(f"@{me.username} id={me.id} name={me.first_name!r} can_join_groups={me.can_join_groups}")

# %% 3. Pick a destination chat
# Private chat: chat_id == your Telegram user id. Press Start on the bot first, then send /whoami to read it.
CHAT_ID = 7279908526
assert CHAT_ID, "set CHAT_ID to your numeric Telegram user id (send /whoami to the bot)"
print("CHAT_ID =", CHAT_ID)

# %% 4. Plain + formatted message
# msg = await bot.send_message(CHAT_ID, "Hello from the notebook 👋\n<b>bold</b> <i>italic</i> <code>code</code>")
msg = await bot.send_message(CHAT_ID, "this is cool, really")
# msg = await bot.send_message(CHAT_ID, "this is cool", disable_notification=True)
print("sent message_id", msg.message_id)

# %% 5. Reply to / edit / delete that message
await bot.send_message(CHAT_ID, "This replies to the previous one", reply_to_message_id=msg.message_id)
# await bot.edit_message_text("Hello from the notebook (<b>edited</b>)", chat_id=CHAT_ID, message_id=msg.message_id)
# await bot.delete_message(CHAT_ID, msg.message_id)


# %% 5a. Delete a message
# Bots can delete their own messages (and, in private chats, the user's) if they are < 48 hours old.
# Deleting is silent: no notification, the message just disappears for both sides.
import asyncio  # noqa: E402

doomed = await bot.send_message(CHAT_ID, "This message will self-destruct in 5s 💣")
await asyncio.sleep(5)
ok = await bot.delete_message(chat_id=CHAT_ID, message_id=doomed.message_id)
print("deleted:", ok)
# Any earlier message by id works too, e.g. the one from cell 4: await bot.delete_message(CHAT_ID, msg.message_id)
# Several at once (1-100 ids): await bot.delete_messages(CHAT_ID, [id1, id2])

# %% 5b. Draft message: stream a live "typing out" preview, then send the real message
# Drafts are ephemeral (~30s preview, private chats only) and never stored in the chat; the final
# send_message is what persists (and what notifies). Same draft_id -> updates animate in place.
draft_id = 1
await bot.send_message_draft(chat_id=CHAT_ID, draft_id=draft_id, text="")  # empty text = "Thinking…" placeholder
await asyncio.sleep(2)
text = ""
for word in "Your order #1042 is ready for pickup at Demo Kitchen.".split():
    text += word + " "
    await bot.send_message_draft(chat_id=CHAT_ID, draft_id=draft_id, text=text)
    await asyncio.sleep(0.5)
final = await bot.send_message(CHAT_ID, text.strip())
print("draft finalised as message_id", final.message_id)

# %% 5c. Edit a sent message in place: a live delivery tracker
# Done steps are struck through (<s>), only the current step is shown (bold), future steps stay hidden.
# The ETA uses <tg-time format="r">: the user's app renders it as "in 8 minutes" and keeps it counting
# down by itself, so we don't spend edits on it. Edits are silent and flood-limited per chat (~20/min in
# practice): keep a few seconds between edits and, on TelegramRetryAfter, wait as told.
# Re-sending identical text + markup raises "message is not modified", so every frame must differ.
import time  # noqa: E402

from aiogram.exceptions import TelegramRetryAfter  # noqa: E402

STEPS = ["🧾 Order received", "👨‍🍳 Preparing", "🛵 Rider picked up", "📍 Nearby", "✅ Delivered"]
eta = int(time.time()) + 8 * 60


def tracker(step: int) -> str:
    done = [f"<s>{s}</s>" for s in STEPS[:step]]
    current = f"<b>{STEPS[step]}</b>" if step == len(STEPS) - 1 else f"<b>{STEPS[step]}…</b>"
    footer = "" if step == len(STEPS) - 1 else f'\n\n<i>Arriving <tg-time unix="{eta}" format="r">in ~8 min</tg-time></i>'
    return "<b>Order #1042</b>\n\n" + "\n".join([*done, current]) + footer


async def edit_with_backoff(text: str, message_id: int):
    try:
        await bot.edit_message_text(text, chat_id=CHAT_ID, message_id=message_id)
    except TelegramRetryAfter as e:
        print(f"flood control: waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        await bot.edit_message_text(text, chat_id=CHAT_ID, message_id=message_id)


live = await bot.send_message(CHAT_ID, tracker(0))
for step in range(1, len(STEPS)):  # 4 edits, 3s apart
    await asyncio.sleep(3)
    await edit_with_backoff(tracker(step), live.message_id)

# Edits can't carry effects or alerts, so the finale is a NEW message: it notifies, and plays a full-screen
# effect (private chats only). Effect ids aren't listed in the Bot API docs; this one is the commonly
# used 🎉 id. If Telegram rejects it ("EFFECT_ID_INVALID"), drop message_effect_id.
await bot.send_message(CHAT_ID, "Your order has arrived. Enjoy! 🍽️", reply_to_message_id=live.message_id,
                       message_effect_id="5046509860389126442")
print("tracker finished on message_id", live.message_id)
# Other edits: edit_message_reply_markup (buttons only), edit_message_caption (media captions),
# edit_message_live_location (moving map pin; needs send_location(..., live_period=...)).

# %% 5d. Restaurant order card: ONE message holding the order, its status and its buttons
# The status line at the top and the buttons change together in a single edit_message_text call
# (text + reply_markup = one edit, so it costs one unit of the flood limit). Dummy data only.
# Buttons: Telegram allows far more than WhatsApp's 3 - in practice up to 100 per message and 8 per row
# (Telegram's limits, not stated in the Bot API docs). callback_data is max 64 bytes.
# Taps here only spin briefly: the running app has no handler for "card:*" yet.
import asyncio  # noqa: E402, F811
from datetime import datetime, timedelta  # noqa: E402

from aiogram.exceptions import TelegramRetryAfter  # noqa: E402, F811
from aiogram.utils.keyboard import InlineKeyboardBuilder  # noqa: E402

ORDER = {
    "ref": "DEMO-ORDR-21", "rest": "Kitchen",
    # Enough items to overflow the ~3 lines an expandable quote shows while collapsed.
    "items": [("Vegetable Biryani", 1, 12.56), ("Mango Lassi", 1, 2.70), ("Garlic Naan", 2, 3.20),
              ("Paneer Tikka", 1, 7.95), ("Onion Bhaji", 1, 4.50), ("Raita", 1, 1.95)],
    "rider": "Demo Rider", "rider_phone": "+447700900123", "code": "39",
    "customer": "1 Demo Street, Salisbury SP1 3TA", "customer_phone": "+447700900456",
    "live_url": "https://example.com/live-location-map/DEMO-ORDR-21",
}
pickup = datetime.now() + timedelta(minutes=10)
CARD_STATUS = [
    "🆕 <b>New order</b> - please confirm",
    "👨‍🍳 <b>Preparing</b> - pick a ready time",
    "🔔 <b>Ready</b> - rider notified",
    "🛵 <b>Picked up</b> - on the way",
    "✅ <b>Delivered</b>",
]


def order_card(step: int) -> str:
    o = ORDER
    items = "\n".join(f"• {q} × {name}  -  £{price:.2f}" for name, q, price in o["items"])
    total = sum(q * price for _, q, price in o["items"])
    pickup_tag = f'<tg-time unix="{int(pickup.timestamp())}" format="t">{pickup:%H:%M}</tg-time>'
    lines = [
        f"<b>Order #{o['ref']}</b> ({o['rest']})",
        f"Status: {CARD_STATUS[step]}",
        "",
        # Accordion: Telegram shows the first ~3 lines of an expandable quote; the reader taps to expand.
        f"<blockquote expandable><b>Items ({len(o['items'])})</b>\n{items}</blockquote>",
        f"<b>Total:</b> £{total:.2f}", "",
        "<b>Delivery details</b>",
        f"⏰ Pickup time - <b>{pickup_tag}</b>",
        f"🛵 Rider - <b>{o['rider']}</b> {o['rider_phone']}",
        f"🔢 Confirmation code - <tg-spoiler>{o['code']}</tg-spoiler>",  # tap to reveal
        f"🏠 Customer - {o['customer']} {o['customer_phone']}",
    ]
    if step >= 3:
        lines.append(f'📍 <a href="{o["live_url"]}">Live location</a>')
    return "\n".join(lines)


def card_buttons(step: int):
    kb = InlineKeyboardBuilder()
    ref = ORDER["ref"]
    if step == 0:
        kb.button(text="✅ Accept", callback_data=f"card:{ref}:accept")
        kb.button(text="❌ Decline", callback_data=f"card:{ref}:decline")
        kb.adjust(2)  # both on one row
    elif step == 1:
        kb.button(text="Ready - Notify Rider", callback_data=f"card:{ref}:ready")
        for mins in (10, 20, 30):
            kb.button(text=f"{datetime.now() + timedelta(minutes=mins):%H:%M} (+{mins}m)", callback_data=f"card:{ref}:t{mins}")
        kb.button(text="❌ Cancel order", callback_data=f"card:{ref}:cancel")
        kb.adjust(1, 3, 1)  # 1 wide button, 3 time slots in a row, 1 wide button
    elif step in (2, 3):
        kb.button(text="⚠️ Report a problem", callback_data=f"card:{ref}:issue")
        kb.button(text="📍 Track rider", url=ORDER["live_url"])  # URL buttons open a link, no callback
        kb.adjust(2)
    return kb.as_markup() if step < len(CARD_STATUS) - 1 else None  # delivered: buttons removed


async def edit_card(step: int, message_id: int):
    kwargs = dict(chat_id=CHAT_ID, message_id=message_id, reply_markup=card_buttons(step))
    try:
        await bot.edit_message_text(order_card(step), **kwargs)
    except TelegramRetryAfter as e:
        print(f"flood control: waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        await bot.edit_message_text(order_card(step), **kwargs)


card = await bot.send_message(CHAT_ID, order_card(0), reply_markup=card_buttons(0))
for step in range(1, len(CARD_STATUS)):  # 4 edits, 4s apart
    await asyncio.sleep(4)
    await edit_card(step, card.message_id)
print("order card message_id", card.message_id)

# %% 7. Ad-hoc keyboard of your own
kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Docs", url="https://core.telegram.org/bots/api")],
    [InlineKeyboardButton(text="Ping", callback_data="demo:menu")],
])
await bot.send_message(CHAT_ID, "Custom keyboard", reply_markup=kb)

# %% 7a. Buttons INSIDE the text (Telegram 13 / aiogram 3.31.0)
# Unlike cell 7's keyboard below the message, RichTextButton sits between words.
# https://docs.aiogram.dev/en/v3.31.0/api/types/rich_text_button.html
# https://docs.aiogram.dev/en/v3.31.0/api/methods/edit_message_text.html
# The main bot's scratchpad router handles the taps through its existing webhook.
# Run the app with the new router mounted, then send /scratchpad → Buttons inside text.
from channels.telegram.rest_admin.scratchpad import rich_button_message  # noqa: E402

await bot.send_rich_message(chat_id=CHAT_ID, rich_message=rich_button_message())

# %% 8. Reply keyboard (location/contact request) and removing it
rk = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Share location", request_location=True)]],
                         resize_keyboard=True, one_time_keyboard=True)
await bot.send_message(CHAT_ID, "Share your location:", reply_markup=rk)
# await bot.send_message(CHAT_ID, "keyboard removed", reply_markup=ReplyKeyboardRemove())

# %% 9. Send a map pin, a venue, a contact, a dice
await bot.send_location(CHAT_ID, latitude=51.5014, longitude=-0.1419)
await bot.send_venue(CHAT_ID, 51.5014, -0.1419, title="Buckingham Palace", address="London SW1A 1AA")
await bot.send_contact(CHAT_ID, phone_number="+447700900123", first_name="Demo", last_name="Rider")
await bot.send_dice(CHAT_ID, emoji="🎲")

# %% 10. Files: photo / document from bytes (use FSInputFile(path), a URL, or a file_id too)
await bot.send_document(CHAT_ID, BufferedInputFile(b"id,name\n1,demo\n", "demo.csv"), caption="A CSV")

# %% 15. Error handling: what failure looks like (blocked bot, bad chat, etc.)
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter  # noqa: E402, F811

try:
    await bot.send_message(1, "this chat does not exist for the bot")
except TelegramForbiddenError as e:
    print("forbidden (user blocked the bot / never started it):", e)
except TelegramRetryAfter as e:
    print("rate limited, wait", e.retry_after, "s")
except TelegramAPIError as e:
    print("other API error:", type(e).__name__, e)

# %% 16. Cleanup: close the HTTP session (run last; re-run cell 1 to start again)
await bot.session.close()
