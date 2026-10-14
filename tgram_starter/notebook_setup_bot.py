# %% [markdown]
# # Bot setup: register the webhook (run once per environment / URL change)
# Run cell by cell (VS Code "Run Cell", Jupyter, or `ipython`). Cells use top-level `await`.
# Interpreter: `tgram_starter/.venv` (`uv sync --project tgram_starter`).
#
# What this does: tells Telegram *where to POST updates* (your FastAPI `/telegram/webhook`)
# and which secret header to send. Telegram only calls public HTTPS URLs (ports 443, 80, 88, 8443),
# so put wherever your app is hosted in `TGRAM_WEBHOOK_BASE_URL` (no trailing slash).
# These calls hit the REAL Bot API. Set/delete changes live behaviour for this bot.

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
assert settings.webhook_base_url.startswith("https://"), "set TGRAM_WEBHOOK_BASE_URL to a public https:// URL"
assert settings.webhook_secret, "set TGRAM_WEBHOOK_SECRET"
dp = build_dispatcher(settings)
await bot.set_webhook(
    settings.webhook_url,
    secret_token=settings.webhook_secret,                 # echoed back in X-Telegram-Bot-Api-Secret-Token
    allowed_updates=dp.resolve_used_update_types(),       # only the update types our handlers use
    drop_pending_updates=False,                           # keep anything queued while the webhook was down
)
print("webhook set ->", settings.webhook_url)

# %% 5. Verify it took (and that Telegram can reach the app)
info = await bot.get_webhook_info()
print("url:                ", info.url)
print("pending updates:    ", info.pending_update_count)
print("last error:         ", info.last_error_message, info.last_error_date)
print("allowed_updates:    ", info.allowed_updates)
assert info.url == settings.webhook_url, "Telegram has a different URL than the one in settings"

# %% 6. Optional: bot commands shown in the Telegram "/" menu (same as BotFather /setcommands)
from aiogram.types import BotCommand  # noqa: E402

await bot.set_my_commands([
    BotCommand(command="start", description="Start / claim an invite"),
    BotCommand(command="menu", description="Interactive demo menu"),
    BotCommand(command="whoami", description="Show my Telegram ids and link status"),
    BotCommand(command="format", description="Formatting sample"),
    BotCommand(command="typing", description="Typing indicator demo"),
    BotCommand(command="help", description="List commands"),
])
print(await bot.get_my_commands())

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
