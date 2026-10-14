# %% [markdown]
# # Telegram bot scratchpad
# Run cell by cell (VS Code "Run Cell", Jupyter, or `ipython`). Cells use top-level `await`.
# Open the repo root as the working directory. Needs `tgram_starter/.env_local` (see README).
# Kernel/interpreter: pick `tgram_starter/.venv` (created by `uv sync --project tgram_starter`).
#
# Rules of thumb:
# - Sending to a chat only works after that person pressed Start on the bot (or you did).
# - Webhook registration lives in notebook_setup_bot.py. This notebook only sends and inspects.
# - This talks to the REAL Bot API. Anything you send is really sent.

# %% 1. Setup: imports, settings, bot
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "tgram_starter").is_dir())
sys.path.insert(0, str(ROOT))  # so `import tgram_starter` works from any cwd

from aiogram.types import (  # noqa: E402
    BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,  # noqa: F401 (used in commented cell)
)

from tgram_starter.bot_factory import build_bot  # noqa: E402
from tgram_starter.config import get_settings  # noqa: E402
from tgram_starter.keyboards import order_offer  # noqa: E402

settings = get_settings()
bot = build_bot(settings)  # HTML parse mode by default
print("token set:", bool(settings.bot_token), "| username:", settings.bot_username, "| admins:", settings.admin_ids)

# %% 2. Who am I? (validates the token)
me = await bot.get_me()
print(f"@{me.username} id={me.id} name={me.first_name!r} can_join_groups={me.can_join_groups}")

# %% 3. Pick a destination chat
# Private chat: chat_id == your Telegram user id. Press Start on the bot first!
# Default: first admin id from TGRAM_ADMIN_IDS. Override by assigning CHAT_ID directly.
CHAT_ID = next(iter(settings.admin_ids), None)
# CHAT_ID = 123456789
print("CHAT_ID =", CHAT_ID)

# %% 4. Plain + formatted message
msg = await bot.send_message(CHAT_ID, "Hello from the notebook 👋\n<b>bold</b> <i>italic</i> <code>code</code>")
print("sent message_id", msg.message_id)

# %% 5. Reply to / edit / delete that message
await bot.send_message(CHAT_ID, "This replies to the previous one", reply_to_message_id=msg.message_id)
await bot.edit_message_text("Hello from the notebook (<b>edited</b>)", chat_id=CHAT_ID, message_id=msg.message_id)
# await bot.delete_message(CHAT_ID, msg.message_id)

# %% 6. Inline keyboard (buttons wired to the running bot's callback handlers)
# Only reacts if the FastAPI app is running and the webhook is set (notebook_setup_bot.py). Otherwise buttons just spin.
await bot.send_message(CHAT_ID, "🛵 <b>Notebook order offer</b>", reply_markup=order_offer(order_id=777))

# %% 7. Ad-hoc keyboard of your own
kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Docs", url="https://core.telegram.org/bots/api")],
    [InlineKeyboardButton(text="Ping", callback_data="demo:menu")],
])
await bot.send_message(CHAT_ID, "Custom keyboard", reply_markup=kb)

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

# %% 11. Invites on the RUNNING app (its dict is the live one): create one via HTTP
# Needs the app running + reachable at TGRAM_WEBHOOK_BASE_URL and TGRAM_ADMIN_API_KEY set.
import httpx  # noqa: E402

API = settings.webhook_base_url
HEADERS = {"X-Admin-Key": settings.admin_api_key}
r = httpx.post(f"{API}/invites", params={"phone_number": "+44 7700 900123"}, headers=HEADERS, timeout=10)
r.raise_for_status()
print(r.json()["link"])  # send this to the person; they tap Start

# %% 12. List invites on the running app (watch status flip pending -> claimed after they tap Start)
for row in httpx.get(f"{API}/invites", headers=HEADERS, timeout=10).json():
    print(row["invite_code"], row["phone_number"], row["status"], row["telegram_user_id"], row["telegram_chat_id"])

# %% 13. Proactive message to a linked user through the running app
# Works only after they pressed Start (that's what stores their chat id).
# r = httpx.post(f"{API}/send", params={"telegram_user_id": 123456789, "text": "hello"}, headers=HEADERS, timeout=10)
# print(r.status_code, r.json())

# %% 14. Local-only invite logic (this kernel's own dict; NOT shared with the running app)
from tgram_starter import invites  # noqa: E402

row = invites.create_invite("+44 7700 900123", settings.invite_ttl_hours)
print(invites.invite_link(settings.bot_username, row["invite_code"]))
print(invites.claim_invite(row["invite_code"], user_id=1, chat_id=1, username="demo", first_name="Demo", language_code="en")[0])
print(invites.find_by_telegram_user(1))

# %% 15. Error handling: what failure looks like (blocked bot, bad chat, etc.)
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter  # noqa: E402

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
