# %% [markdown]
# # Bot setup: register the webhook (run once per environment / URL change)
# Run cell by cell (VS Code "Run Cell", Jupyter, or `ipython`). Cells use top-level `await`.
# Interpreter: `tgram_starter/.venv` (`uv sync --project tgram_starter`).
#
# What this does: tells Telegram *where to POST updates* (your FastAPI `/telegram/webhook`)
# and which secret header to send. Telegram only calls public HTTPS URLs (ports 443, 80, 88, 8443),
# so put wherever your app is hosted in `TGRAM_WEBHOOK_BASE_URL` (no trailing slash).
# These calls hit the REAL Bot API. Set/delete changes live behaviour for this bot.
#
# Order of play (first time):  1-2 token check -> 4 set webhook -> 5 verify -> 6 commands
#   -> 6a mini-app preflight -> 6c send yourself the launch button (6b = permanent menu button, optional).
# Cell 4 and 6a need the app already running at your public HTTPS URL (the branch with /miniapp deployed).

# %% 1. Load settings and build the bot
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "tgram_starter").is_dir())
sys.path.insert(0, str(ROOT))  # so `import tgram_starter` works from any cwd

from tgram_starter.bot_factory import build_bot, build_dispatcher  # noqa: E402
from tgram_starter.config import get_settings  # noqa: E402

settings = get_settings()
bot = build_bot(settings)
print("token set:     ", bool(settings.bot_token))
print("secret set:    ", bool(settings.webhook_secret))
print("webhook URL:   ", settings.webhook_url if settings.webhook_base_url else "(TGRAM_WEBHOOK_BASE_URL not set)")

# %% 2. Validate the token
me = await bot.get_me()
print(f"OK token valid -> @{me.username} id={me.id} name={me.first_name!r}")
if settings.bot_username and settings.bot_username != me.username:
    print(f"WARNING: TGRAM_BOT_USERNAME={settings.bot_username!r} but the token belongs to @{me.username}")

# %% 3. What does Telegram currently have? (read-only)
info = await bot.get_webhook_info()
print(info.model_dump_json(indent=2, exclude_none=True))

# Look at: url (empty = no webhook), pending_update_count, last_error_date/last_error_message.

# %% 4. SET the webhook  (the step you came here for)
# assert settings.webhook_base_url.startswith("https://"), "set TGRAM_WEBHOOK_BASE_URL to a public https:// URL"
# assert settings.webhook_secret, "set TGRAM_WEBHOOK_SECRET"
dp = build_dispatcher(settings)
callback_url = "https://rider-agent-test.ordelo.app/telegram/webhook"
await bot.set_webhook(
    # settings.webhook_url,
    url=callback_url,
    secret_token=settings.webhook_secret,                 # echoed back in X-Telegram-Bot-Api-Secret-Token
    allowed_updates=dp.resolve_used_update_types(),       # only the update types our handlers use
    drop_pending_updates=False,                           # keep anything queued while the webhook was down
)
print("webhook set ->", callback_url)

# %% 5. Verify it took (and that Telegram can reach the app)
info = await bot.get_webhook_info()
print("url:                ", info.url)
print("pending updates:    ", info.pending_update_count)
print("last error:         ", info.last_error_message, info.last_error_date)
print("allowed_updates:    ", info.allowed_updates)
assert info.url == callback_url, "Telegram has a different URL than the one set in step 4"

# %% 6. Optional: bot commands shown in the Telegram "/" menu (same as BotFather /setcommands)
from aiogram.types import BotCommand  # noqa: E402

await bot.set_my_commands([
    BotCommand(command="start", description="Start / claim an invite"),
    BotCommand(command="menu", description="Interactive demo menu"),
    BotCommand(command="app", description="Open the Demo Kitchen mini app"),
    BotCommand(command="whoami", description="Show my Telegram ids and link status"),
    BotCommand(command="format", description="Formatting sample"),
    BotCommand(command="typing", description="Typing indicator demo"),
    BotCommand(command="help", description="List commands"),
])
print(await bot.get_my_commands())

# %% 6a. MINI APP preflight: is the page reachable over HTTPS from the public internet?
# Run this BEFORE 6b/6c. Telegram opens the URL from the user's phone, so "works on localhost" is not enough.
import httpx  # noqa: E402

base = settings.webhook_base_url or callback_url.rsplit("/telegram/webhook", 1)[0]
MINIAPP_URL = settings.miniapp_url or base + "/miniapp/"
print("MINIAPP_URL =", MINIAPP_URL)
assert MINIAPP_URL.startswith("https://"), "Telegram only opens https:// mini apps (set TGRAM_WEBHOOK_BASE_URL or TGRAM_MINIAPP_URL)"

page = httpx.get(MINIAPP_URL, timeout=10, follow_redirects=True)
assert page.status_code == 200 and "telegram-web-app.js" in page.text, (
    f"page check failed ({page.status_code}): is the deployed app running THIS branch (it needs the /miniapp routes) and restarted?")
print("page            ->", page.status_code, "OK (serves the mini app HTML)")

api = httpx.get(MINIAPP_URL.rstrip("/") + "/api/menu", timeout=10)  # no initData on purpose
assert api.status_code == 401, f"expected 401 without signed initData, got {api.status_code}: the API must reject unsigned calls"
print("api w/o initData ->", api.status_code, "OK (rejects unsigned calls)")

# %% 6b. Mini app: put a "Demo Kitchen" button next to the message box (the bot's menu button)
from aiogram.types import MenuButtonWebApp, WebAppInfo  # noqa: E402

await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Demo Kitchen", web_app=WebAppInfo(url=MINIAPP_URL)))
print("menu button ->", MINIAPP_URL)
print(await bot.get_chat_menu_button())
# This sets the DEFAULT for all chats with the bot. Undo: await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
# Per-chat instead of global: await bot.set_chat_menu_button(chat_id=TEST_CHAT_ID, menu_button=...)

# %% 6c. Send YOURSELF the launch button (fastest way to try it; no /app command or webhook needed)
# Prerequisite: you pressed Start on the bot once. Set TEST_CHAT_ID to your Telegram user id if TGRAM_ADMIN_IDS is empty.
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: E402

TEST_CHAT_ID = next(iter(settings.admin_ids), None)
# TEST_CHAT_ID = 123456789
assert TEST_CHAT_ID, "set TEST_CHAT_ID (message @userinfobot to find your numeric id)"
await bot.send_message(
    TEST_CHAT_ID,
    "Tap to open the mini app inside Telegram:",
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🍽 Open Demo Kitchen", web_app=WebAppInfo(url=MINIAPP_URL))]]),
)
print("sent launch button to", TEST_CHAT_ID)

# %% 7. Optional: smoke-test the live endpoint over HTTP (app must be running and reachable)
import httpx  # noqa: E402

r = httpx.get(f"{settings.webhook_base_url}/health", timeout=10)
print(r.status_code, r.text)
# A wrong secret must be rejected; if this prints 200 your app is not checking the header.
r = httpx.post(settings.webhook_url, json={"update_id": 0}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, timeout=10)
print("bad secret ->", r.status_code, "(expected 403)")

# %% 8. DELETE the webhook (stops all delivery to the app; updates then queue at Telegram for ~24h)
# await bot.delete_webhook(drop_pending_updates=False)
# print(await bot.get_webhook_info())

# %% 9. Cleanup: close the HTTP session (re-run cell 1 to start again)
await bot.session.close()
