# %% [markdown]
# # Restaurant-admin bot setup: register the webhook (run once per environment / URL change)
# Run cell by cell (VS Code "Run Cell", Jupyter, or `ipython`). Cells use top-level `await`.
# Run from the repo root with the main project .venv, PYTHONPATH="$PWD" and AWS_SETTINGS_* set
# (see docs/local-testing-runbook.md section 1): importing `config` loads every OrdeloAgent setting.
#
# What this does: tells Telegram *where to POST updates* (OrdeloAgent's /telegram/rest-admin/webhook)
# and which secret header to send. Telegram only calls public HTTPS URLs (ports 443, 80, 88, 8443),
# so tgram_rest_admin_webhook_base_url must be your public (tunnel or deployed) base URL.
# These calls hit the REAL Bot API. Setting/deleting the webhook changes live behaviour for this bot.
#
# !! The dev bot is SHARED with tgram_starter (decision D8). A bot has exactly ONE webhook:
#    whichever URL was set last receives every update. Cell 8 hands the bot back to the starter.
# NEVER set the webhook from app startup; it is always an explicit step here.
#
# Order of play (first time):  1-2 token check -> 3 current webhook -> 4 set -> 5 verify -> 6 commands -> 7 smoke test

# %% 1. Setup: settings and bot (from config, built from the AWS secret / TGRAM_REST_ADMIN_* env vars)
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "channels" / "telegram").is_dir())

sys.path.insert(0, str(ROOT))

from channels.telegram.bots import build_rest_admin_dispatcher  # noqa: E402
from channels.telegram.rest_admin.commands import REST_ADMIN_COMMANDS  # noqa: E402
from config import rest_admin_bot as bot, tgram_rest_admin_settings as settings  # noqa: E402
# %%
BOT_KEY = settings.bot_key  # "rest_admin"
print("bot_key:      ", BOT_KEY)
print("token set:    ", bool(settings.bot_token))
print("secret set:   ", bool(settings.webhook_secret))
print("webhook URL:  ", settings.webhook_url or "(tgram_rest_admin_webhook_base_url not set)")

# %% 2. Validate the token
me = await bot.get_me()
print(f"OK token valid -> @{me.username} id={me.id} name={me.first_name!r}")
if settings.bot_username and settings.bot_username != me.username:
    print(f"WARNING: bot_username={settings.bot_username!r} but the token belongs to @{me.username}")

# %% 3. What does Telegram currently have? (read-only)
info = await bot.get_webhook_info()
print(info.model_dump_json(indent=2, exclude_none=True))
# Look at: url (empty = no webhook), pending_update_count, last_error_date/last_error_message.

# %% 4. SET the webhook to OrdeloAgent  (the step you came here for)
# Re-run this cell after adding handlers for new update types (e.g. callback_query for the invite buttons):
# allowed_updates below is computed from the handlers, and Telegram only sends what is listed.
assert settings.webhook_url.startswith("https://"), "set tgram_rest_admin_webhook_base_url to a public https:// URL"
dp = build_rest_admin_dispatcher(settings)
await bot.set_webhook(
    url=settings.webhook_url,
    secret_token=settings.webhook_secret.get_secret_value(),  # echoed back in X-Telegram-Bot-Api-Secret-Token
    allowed_updates=dp.resolve_used_update_types(),           # only the update types our handlers use
    drop_pending_updates=False,                               # keep anything queued while the webhook was down
)
print("webhook set ->", settings.webhook_url)

# %% 5. Verify it took (and that Telegram can reach the app)
info = await bot.get_webhook_info()
print("url:                ", info.url)
print("pending updates:    ", info.pending_update_count)
print("last error:         ", info.last_error_message, info.last_error_date)
print("allowed_updates:    ", info.allowed_updates)
assert info.url == settings.webhook_url, "Telegram has a different URL than the one set in step 4"

# %% 6. Bot commands shown in the Telegram "/" menu (same as BotFather /setcommands)
await bot.set_my_commands(REST_ADMIN_COMMANDS)
print(await bot.get_my_commands())

# %% 7. Smoke-test the live endpoint over HTTP (the app must be running and reachable)
import httpx  # noqa: E402

# A wrong secret must be rejected; if this prints 200 the route is not checking the header.
r = httpx.post(settings.webhook_url, json={"update_id": 0}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}, timeout=10)
print("bad secret ->", r.status_code, "(expected 403; 404 means the running app has no such bot route)")

# %% 8. HAND THE BOT BACK to tgram_starter (stops OrdeloAgent receiving updates for this bot)
# Fill STARTER_URL / STARTER_SECRET from tgram_starter/.env (TGRAM_WEBHOOK_BASE_URL + "/telegram/webhook",
# TGRAM_WEBHOOK_SECRET). Print nothing secret. Uncomment to run.
# STARTER_URL = "https://<starter-host>/telegram/webhook"
# STARTER_SECRET = "<value of TGRAM_WEBHOOK_SECRET in tgram_starter/.env>"
# await bot.set_webhook(url=STARTER_URL, secret_token=STARTER_SECRET, drop_pending_updates=False)
# print((await bot.get_webhook_info()).url)

# %% 9. DELETE the webhook (stops all delivery to any app; updates then queue at Telegram for ~24h)
# await bot.delete_webhook(drop_pending_updates=False)
# print(await bot.get_webhook_info())

# %% 10. Cleanup: close the HTTP session (re-run cell 1 to start again)
await bot.session.close()
