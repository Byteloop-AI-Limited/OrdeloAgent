# Telegram restaurant-admin bot — scaffold plan (step 1)

**Status:** Approved for implementation planning, 15 October 2026. Nothing here is implemented yet.
**Repository:** `OrdeloAgent` (this repo). `tgram_starter/` is **not modified**.
**Sources:** [`docs/ordelo_telegram_implementation_handoff.md`](../docs/ordelo_telegram_implementation_handoff.md),
[ADR 0011](../docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md),
[ADR 0012](../docs/adr/0012-rider-threads-follow-dispatch-assignments.md) (rider work, deferred),
`tgram_starter/` (reference only), project skill `.claude/skills/telegram-api/`.

---

## 0. What this step delivers

Mount a **restaurant-admin Telegram bot** (`bot_key = "rest_admin"`) on the existing FastAPI app
(`watomation/fapp_ordelo_agent.py`). This step adds the plumbing only: settings from AWS Secrets Manager, a bot
registry that builds a separate Bot and Dispatcher for each bot, a thin webhook route, three read-only commands,
two notebooks and tests. The rider bot comes later and plugs into the same registry.

### Decisions (grilling session, 15 Oct 2026)

| # | Decision |
|---|---|
| D1 | Copy the starter's patterns into the ADR 0011 layout (`channels/telegram/`). **Never import `tgram_starter`** from production code (its README promises "Nothing outside this folder imports it"). The starter stays unchanged. |
| D2 | **Plumbing only.** No invites, order card, Mini App, echo or `/send` endpoints. Nothing keeps state in process memory, because gunicorn runs up to 3 workers (`gunicorn_conf.py:9`, `max_workers_str = "3"`). |
| D3 | One `TgramBotSettings` (pydantic-settings) class, built once per bot from prefixed `agent_env` keys `tgram_<bot_key>_*`. File: `config/tgram_setting.py`, singular to match `waba_setting.py`. |
| D3a | **No admin ID list in the settings.** Restaurant admins come from `restaurant_master.admins` (phone numbers; see `ordelo_datamodels/restaurant_master_pymodel.py:33`, `RestaurantMaster.get_admins_for`). |
| D4 | **Linking is not in this step.** `/start` replies "not linked yet". The next step links accounts by shared contact (see §9). |
| D5 | The webhook handles updates **inline**: secret check, time limit, log failures, always reply 200. A durable inbox (`telegram_inbox`, keyed `(bot_key, update_id)`) is a **hard gate before the first action that changes state** (order acceptance and so on). |
| D6 | **Superseded 15 Oct 2026: token and webhook secret are now required; startup fails if missing.** Original: Telegram keys are **optional**. The bot is enabled only when the token and webhook secret are both present. A disabled bot is not built, and its route returns 404. WhatsApp startup must never depend on Telegram. |
| D7 | Notebooks go in `notebooks/telegram/` and run from the main project `.venv`. Mini App and rider demo cells are dropped. |
| D8 | **Reuse the starter's existing dev bot** (its token is in `tgram_starter/.env`) as the restaurant-admin **test** bot. The rider bot gets created later. |
| D9 | `config/__init__.py` exports `tgram_rest_admin_settings` and `rest_admin_bot: Bot \| None`, so `from config import rest_admin_bot` works the way `_async_wa_client` does. The Bot is built at import (no connection opens until the first API call). The **Dispatcher stays out of `config`** to avoid circular imports. |
| D9a | Use `rest_admin` everywhere: `bot_key="rest_admin"`, secret keys `tgram_rest_admin_*`, route `/telegram/rest-admin/webhook`. |
| D10 | Focused contract tests in `tests/config/` and `tests/channels/telegram/`, plus the smoke-import list and `ruff`. |

### Out of scope (do not build)

Invites and `/start <token>`; contact-share linking; the `telegram_identities`, `telegram_inbox` and message-index
tables; order acceptance and pickup-time actions; reminders and acknowledgement; the operations-messaging port
(`ordelo/ops_messaging/`); the rider bot; the Mini App; `scripts/telegram_webhook.py`; setting the webhook on startup
(**never** do this; see handoff §9).

---

## 1. Target file map

```text
NEW   config/tgram_setting.py                         TgramBotSettings, build_bot, tgram_rest_admin_settings, rest_admin_bot
EDIT  config/__init__.py                              re-export the two values + TgramBotSettings
NEW   channels/__init__.py                            empty
NEW   channels/telegram/__init__.py                   short docstring only
NEW   channels/telegram/bots.py                       TelegramBot dataclass, registry builder, dispatcher factory, close
NEW   channels/telegram/errors.py                     stale-callback error handler (from tgram_starter/bot_factory.py:40-47)
NEW   channels/telegram/keyboards.py                  contact_request_kb (from tgram_starter/keyboards.py:60-64), for step 2
NEW   channels/telegram/callbacks.py                  64-byte callback convention + fits_callback_limit()
NEW   channels/telegram/rest_admin/__init__.py        empty
NEW   channels/telegram/rest_admin/commands.py        REST_ADMIN_COMMANDS (BotCommand list) + HELP_TEXT
NEW   channels/telegram/rest_admin/router.py          build_router() factory: /start, /help, /whoami, fallback
NEW   watomation/routers/telegram_webhook.py          POST /telegram/{bot_slug}/webhook
EDIT  watomation/fapp_ordelo_agent.py                 lifespan builds/closes registry; include router
EDIT  pyproject.toml                                  aiogram==3.31.0; add "channels" to wheel packages
EDIT  uv.lock                                         `uv lock` (do not hand-edit)
EDIT  requirements.txt                                add aiogram==3.31.0 if this file is still used for any deploy path
NEW   notebooks/telegram/tgram_setup_bot.py           from tgram_starter/notebook_setup_bot.py
NEW   notebooks/telegram/tgram_scratchpad.py          from tgram_starter/notebook.py
EDIT  tests/conftest.py                               stub tgram_rest_admin_* keys in _STUB_AGENT_ENV
EDIT  tests/test_smoke_imports.py                     add new modules
NEW   tests/config/test_tgram_setting.py
NEW   tests/channels/__init__.py, tests/channels/telegram/__init__.py
NEW   tests/channels/telegram/conftest.py             RecordingSession + update payload builders
NEW   tests/channels/telegram/test_bots.py
NEW   tests/channels/telegram/test_rest_admin_router.py
NEW   tests/watomation/routers/test_telegram_webhook.py
EDIT  docs/adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md   amendments (§8)
EDIT  CONTEXT.md                                      two new terms (§8)
EDIT  docs/local-testing-runbook.md                   short "Telegram restaurant-admin bot" section (§8)
```

Untouched: everything under `tgram_starter/`, including its `.env`, `pyproject.toml` and `.venv`.

---

## 2. Dependencies

`pyproject.toml` (currently lines 4–40 for dependencies and line 66 for the wheel packages):

```toml
dependencies = [
    ...
    # WhatsApp
    "pywa==3.6.1",
    # Telegram (restaurant-admin bot; rider bot later)
    "aiogram==3.31.0",
    ...
]

[tool.hatch.build.targets.wheel]
packages = ["ordelo", "ordelo_datamodels", "watomation", "utils_common", "utils", "config", "channels"]
```

Then run `uv lock && uv sync`. Use the same pin as `tgram_starter/pyproject.toml` (`aiogram==3.31.0`, sdist uploaded
2026-08-26 per `tgram_starter/uv.lock`). Check that `uv lock` doesn't force downgrades of `pydantic`, `aiohttp` or
`fastapi`. aiogram brings in `aiohttp`, `magic-filter` and `aiofiles`. The Dockerfile runs `uv sync --frozen`
(Dockerfile lines 21–28), so the lockfile must be committed.

---

## 3. Settings — `config/tgram_setting.py`

Follow the conventions in `config/waba_setting.py`: module docstring in the house format, `# %%` cells, settings
built from `aws_setting.agent_env`, and a module-level instance. The differences are that the namespace includes the
bot key, the fields are optional, and secrets are `SecretStr`.

### Secret keys (in the AWS secret loaded at `aws_setting.py:108`, `get_agent_env(secret_name="ordelo-agent-env")`)

| Key | Example | Notes |
|---|---|---|
| `tgram_rest_admin_bot_token` | `123456789:AA…` | From BotFather. For test, use the starter bot's token (`TGRAM_BOT_TOKEN` in `tgram_starter/.env`) (D8). |
| `tgram_rest_admin_bot_username` | `my_ordelo_test_bot` | Without the `@`. Used for deep links later and by the notebook's username check. |
| `tgram_rest_admin_webhook_secret` | `secrets.token_urlsafe(32)` | Must match `[A-Za-z0-9_-]{1,256}`. Use a **new** value, not the starter's, so the starter's secret can't drive the service. |
| `tgram_rest_admin_webhook_base_url` | `https://rider-agent-test.ordelo.app` | No trailing slash. Used only by the notebooks and the `webhook_url` property. |

Local fallback: when a key is missing from the secret, environment variables `TGRAM_REST_ADMIN_BOT_TOKEN` and the
others are read through pydantic-settings' `_env_prefix`. Values from the secret win.

### Code

```python
"""
Telegram bot settings for OrdeloAgent.
    . Defines TgramBotSettings: per-bot settings read from agent_env keys `tgram_<bot_key>_*`
    . Keys are optional; a bot is enabled only when its token and webhook secret are present
    . Builds aiogram Bot objects at import (no network until first API call)
    . Exposes the restaurant-admin bot used by channels/telegram and notebooks/telegram
    . Depends on: pydantic_settings, aiogram, loguru, aws_setting
  Classes/Functions:
    . TgramBotSettings
    . build_bot
  Module values:
    . REST_ADMIN_BOT_KEY
    . tgram_rest_admin_settings
    . rest_admin_bot
"""

# %%
import re
from typing import Any, Mapping

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.utils.token import TokenValidationError
from loguru import logger
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aws_setting import agent_env

REST_ADMIN_BOT_KEY = "rest_admin"
_WEBHOOK_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")  # Telegram setWebhook secret_token rule


# %%
class TgramBotSettings(BaseSettings):
    bot_key: str
    bot_token: SecretStr | None = None
    bot_username: str = ""
    webhook_secret: SecretStr | None = None
    webhook_base_url: str = ""

    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("bot_username")
    @classmethod
    def _strip_at(cls, v: str) -> str:
        return v.strip().lstrip("@")

    @field_validator("webhook_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @field_validator("webhook_secret")
    @classmethod
    def _check_secret(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and not _WEBHOOK_SECRET_RE.match(v.get_secret_value()):
            raise ValueError("webhook_secret must match [A-Za-z0-9_-]{1,256}")
        return v

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.webhook_secret)

    @property
    def path_slug(self) -> str:
        return self.bot_key.replace("_", "-")  # rest_admin -> rest-admin

    @property
    def webhook_path(self) -> str:
        return f"/telegram/{self.path_slug}/webhook"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}" if self.webhook_base_url else ""

    @classmethod
    def for_bot(cls, bot_key: str, env: Mapping[str, Any]) -> "TgramBotSettings":
        """Read `tgram_<bot_key>_*` keys from env (agent_env); empty values count as missing."""
        prefix = f"tgram_{bot_key}_"
        values = {
            k[len(prefix):]: v
            for k, v in env.items()
            if k.startswith(prefix) and v not in (None, "")
        }
        # _env_prefix lets local env vars (TGRAM_REST_ADMIN_BOT_TOKEN, ...) fill gaps; init kwargs win.
        return cls(_env_prefix=prefix.upper(), bot_key=bot_key, **values)


def build_bot(settings: TgramBotSettings) -> Bot | None:
    """Bot for an enabled settings object; None (and one log line) otherwise. Never raises."""
    if not settings.enabled:
        logger.info(f"telegram[{settings.bot_key}]: disabled (token or webhook secret missing)")
        return None
    try:
        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    except TokenValidationError:
        logger.error(f"telegram[{settings.bot_key}]: disabled (malformed bot token)")
        return None
    logger.info(f"telegram[{settings.bot_key}]: enabled -> {settings.webhook_path}")
    return bot


# %%
tgram_rest_admin_settings = TgramBotSettings.for_bot(REST_ADMIN_BOT_KEY, agent_env)
rest_admin_bot: Bot | None = build_bot(tgram_rest_admin_settings)
```

Notes for the implementer:
- `_env_prefix` is a supported pydantic-settings init argument. Check that it works with the pinned
  `pydantic-settings` version. If it doesn't, build a subclass on the fly with `model_config = SettingsConfigDict(env_prefix=...)`.
- Never log `bot_token` or `webhook_secret`. `SecretStr` keeps them out of `repr()`.
- `Bot(...)` validates the token format only. `get_me` is never called at import.
- The rider bot later adds one line: `tgram_rider_settings = TgramBotSettings.for_bot("rider", agent_env)`.

### `config/__init__.py`

Add the following to `__all__` (lines 2–19) and to the imports (after line 41, `from .wa_location_setting import …`):

```python
__all__ = [
    ...
    "wa_location_settings",
    "TgramBotSettings",
    "tgram_rest_admin_settings",
    "rest_admin_bot",
]
...
from .tgram_setting import TgramBotSettings, tgram_rest_admin_settings, rest_admin_bot
```

---

## 4. Channel adapter — `channels/telegram/`

Composition rule from ADR 0011: each bot gets a **new Dispatcher and a new router tree**. The starter's
module-level `_dp` singleton (`tgram_starter/bot_factory.py:21-35`) and module-level `router = Router(...)`
objects are exactly what we must not copy. aiogram lets a router belong to only one parent, which is why the starter's
tests have to reset `router._parent_router` (`tgram_starter/tests/test_starter.py:265-271`).

### 4.1 `channels/telegram/errors.py`

This comes from `tgram_starter/bot_factory.py:40-47`:

```python
"""Shared Dispatcher error handlers for every Ordelo Telegram bot."""
from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent
from loguru import logger


async def ignore_stale_callback(event: ErrorEvent):
    # A button tap must be answered within ~15s; late/redelivered taps can't be answered any more.
    if "query is too old" not in event.exception.message:
        raise event.exception
    logger.warning(f"telegram: ignoring stale callback query (update {event.update.update_id})")


def register_error_handlers(dp: Dispatcher) -> None:
    dp.errors.register(ignore_stale_callback, ExceptionTypeFilter(TelegramBadRequest))
```

### 4.2 `channels/telegram/keyboards.py` and `callbacks.py`

- `keyboards.py`: copy `contact_request_kb()` from `tgram_starter/keyboards.py:60-64` without changes. Step 2's
  contact-share linking uses it. Do not copy `main_menu`, `order_offer`, `counter_kb` or the demo `CallbackData`
  classes.
- `callbacks.py`: a docstring stating the convention (one `CallbackData` subclass per action family, a short
  `prefix`, opaque short refs, **64 bytes maximum** after `.pack()`, and authorisation never trusting the packed value),
  plus:

```python
from aiogram.filters.callback_data import CallbackData

CALLBACK_DATA_MAX_BYTES = 64


def fits_callback_limit(data: CallbackData) -> bool:
    return 1 <= len(data.pack().encode()) <= CALLBACK_DATA_MAX_BYTES
```

The first real `CallbackData` class (order accept and the like) arrives with the order actions, not in this step.

### 4.3 `channels/telegram/rest_admin/commands.py`

```python
"""Restaurant-admin bot command menu (published by notebooks/telegram/tgram_setup_bot.py)."""
from aiogram.types import BotCommand

REST_ADMIN_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Start / link this chat to your restaurant"),
    BotCommand(command="help", description="What this bot can do"),
    BotCommand(command="whoami", description="Show your Telegram ids and link status"),
]

HELP_TEXT = "<b>Ordelo restaurant bot</b>\n" + "\n".join(
    f"/{c.command} - {c.description}" for c in REST_ADMIN_COMMANDS
)
```

Keep only restaurant commands here. The rider bot later gets its own `rider/commands.py` (ADR 0011: "An unknown
restaurant command must not fall through to a rider graph").

### 4.4 `channels/telegram/rest_admin/router.py`

Handlers are module-level functions, and `build_router()` registers them on a **new** `Router` each time it's called.
The wording comes from `tgram_starter/handlers/onboarding.py:21-48` and `:67-77` with the invite logic removed.

```python
"""Restaurant-admin bot router factory: deterministic commands only, never a LangGraph agent."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .commands import HELP_TEXT

NOT_LINKED = (
    "Hi! This is the Ordelo restaurant bot.\n"
    "This chat isn't linked to a restaurant yet. Linking is coming soon; "
    "your Ordelo contact will tell you when to press /start again."
)


async def cmd_start(message: Message):
    # Step 2: offer contact_request_kb() and link via restaurant_master.admins.
    await message.answer(NOT_LINKED)


async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


async def cmd_whoami(message: Message):
    u = message.from_user
    lines = [
        f"from_user.id (the person): <code>{u.id}</code>",
        f"chat.id (where we reply):  <code>{message.chat.id}</code>",
        f"username (mutable):        @{escape(u.username or '-')}",
        "Ordelo link: not linked",
    ]
    await message.answer("<pre>" + "\n".join(lines) + "</pre>")


async def fallback(message: Message):
    await message.answer("I don't understand that yet. Try /help.")


def build_router() -> Router:
    router = Router(name="rest_admin")
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_whoami, Command("whoami"))
    router.message.register(fallback, F.text)  # last: swallows any other text
    return router
```

Watch out for HTML escaping: `<pre>` content above holds only integers and an escaped username. Any
user-supplied text added later must go through `html.escape` because the Bot defaults to `ParseMode.HTML`.

### 4.5 `channels/telegram/bots.py`

```python
"""
Telegram bot registry for OrdeloAgent.
    . One TelegramBot (settings + Bot + Dispatcher) per enabled bot_key
    . Fresh Dispatcher and router tree per bot (never shared, never module-level)
    . Built in the FastAPI lifespan; closed on shutdown
  Classes/Functions:
    . TelegramBot
    . build_rest_admin_dispatcher
    . build_registry
    . default_registry
    . find_by_slug
    . close_registry
"""
from dataclasses import dataclass
from typing import Callable, Iterable

from aiogram import Bot, Dispatcher
from loguru import logger

from config.tgram_setting import REST_ADMIN_BOT_KEY, TgramBotSettings

from .errors import register_error_handlers
from .rest_admin.router import build_router as build_rest_admin_router


@dataclass(frozen=True)
class TelegramBot:
    settings: TgramBotSettings
    bot: Bot
    dp: Dispatcher

    @property
    def key(self) -> str:
        return self.settings.bot_key


def build_rest_admin_dispatcher(settings: TgramBotSettings) -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(build_rest_admin_router())
    register_error_handlers(dp)
    dp["tgram_settings"] = settings  # injected into handlers that declare `tgram_settings`
    return dp


DISPATCHER_FACTORIES: dict[str, Callable[[TgramBotSettings], Dispatcher]] = {
    REST_ADMIN_BOT_KEY: build_rest_admin_dispatcher,
    # "rider": build_rider_dispatcher,  # later phase
}


def build_registry(entries: Iterable[tuple[TgramBotSettings, Bot | None]]) -> dict[str, TelegramBot]:
    registry: dict[str, TelegramBot] = {}
    for settings, bot in entries:
        if bot is None:
            continue
        registry[settings.bot_key] = TelegramBot(
            settings=settings, bot=bot, dp=DISPATCHER_FACTORIES[settings.bot_key](settings)
        )
    logger.info(f"telegram: registry built for {sorted(registry) or 'no bots'}")
    return registry


def default_registry() -> dict[str, TelegramBot]:
    from config import rest_admin_bot, tgram_rest_admin_settings

    return build_registry([(tgram_rest_admin_settings, rest_admin_bot)])


def find_by_slug(registry: dict[str, TelegramBot], slug: str) -> TelegramBot | None:
    return next((b for b in registry.values() if b.settings.path_slug == slug), None)


async def close_registry(registry: dict[str, TelegramBot]) -> None:
    for tg in registry.values():
        await tg.bot.session.close()  # never delete/set the webhook here (handoff §9)
```

Why the Dispatcher isn't in `config` (D9): the handlers will soon import domain modules (`ordelo.*`, `utils_common.*`)
that import `config`. If `config` imported the handlers, that would create a circular import.

---

## 5. Webhook route — `watomation/routers/telegram_webhook.py`

This follows `tgram_starter/app.py:57-74` with these changes: the bot is looked up from the trusted registry by the
path slug, the secret comparison uses bytes, there's a time limit, raw payloads are never printed, and a malformed
update doesn't trigger retries.

```python
"""
Telegram webhook ingress for OrdeloAgent (thin route; logic lives in channels/telegram).
    . POST /telegram/{bot_slug}/webhook, e.g. /telegram/rest-admin/webhook
    . 404 for unknown/disabled bots, 403 for a wrong X-Telegram-Bot-Api-Secret-Token
    . Feeds the update to that bot's own Dispatcher inline with a timeout
    . Always 200 after the secret check: Telegram retries non-2xx and a failing update would loop
    . STEP-1 ONLY: no durable inbox. Must add telegram_inbox before any state-changing handler (ADR 0011).
"""
import asyncio
import secrets

from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from channels.telegram.bots import find_by_slug

router = APIRouter(tags=["telegram"])

HANDLER_TIMEOUT_SECS = 25


@router.post("/telegram/{bot_slug}/webhook", include_in_schema=False)
async def telegram_webhook(
    bot_slug: str,
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    tg = find_by_slug(getattr(request.app.state, "telegram_bots", {}), bot_slug)
    if tg is None:
        raise HTTPException(404, "unknown bot")
    expected = tg.settings.webhook_secret.get_secret_value().encode()
    if not secrets.compare_digest(x_telegram_bot_api_secret_token.encode(), expected):
        raise HTTPException(403, "bad secret")

    payload = await request.json()
    try:
        update = Update.model_validate(payload, context={"bot": tg.bot})
    except ValidationError:
        logger.warning(f"telegram[{tg.key}]: invalid update {payload.get('update_id')}")
        return {"ok": True}

    try:
        await asyncio.wait_for(tg.dp.feed_update(tg.bot, update), timeout=HANDLER_TIMEOUT_SECS)
    except Exception:  # includes TimeoutError
        logger.exception(f"telegram[{tg.key}]: handler failed for update {update.update_id}")
    return {"ok": True}
```

### `watomation/fapp_ordelo_agent.py` edits

1. Imports (near lines 37–58):
   ```python
   from channels.telegram.bots import close_registry, default_registry
   from watomation.routers import telegram_webhook
   ```
2. Lifespan (currently lines 124–132):
   ```python
   @asynccontextmanager
   async def lifespan(app):
       app.state.telegram_bots = default_registry()
       task = asyncio.create_task(run_sweeper())
       try:
           yield
       finally:
           task.cancel()
           with suppress(asyncio.CancelledError):
               await task
           await close_registry(app.state.telegram_bots)
   ```
3. Router (after line 162, `app.include_router(web_hooks.router, prefix="/web")`):
   ```python
   app.include_router(telegram_webhook.router)
   ```
4. Update the module docstring bullet list ("Serves Telegram webhooks for the restaurant-admin bot").

Do **not** call `set_webhook` or `delete_webhook` in the lifespan. Local and production restarts would fight over
which server owns the webhook (handoff §9; starter `app.py:42`).

---

## 6. Notebooks — `notebooks/telegram/`

Both notebooks use `# %%` cells with top-level `await` (the repo's ruff config already ignores `F704`). Run them from
the repo root with the main `.venv`, `PYTHONPATH="$PWD"` and `.env` loaded with `envLoad`, as in
`docs/local-testing-runbook.md` §1. Importing `config` loads **every** setting, including the WABA clients and
Supabase (see `config/__init__.py`), so `AWS_SETTINGS_*` must be set.

Shared first cell:

```python
# %% 1. Setup
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "channels" / "telegram").is_dir())
sys.path.insert(0, str(ROOT))

from config import rest_admin_bot as bot, tgram_rest_admin_settings as settings  # noqa: E402

assert bot is not None, "rest_admin bot disabled: add tgram_rest_admin_bot_token + _webhook_secret to the secret"
print("bot_key:", settings.bot_key, "| username:", settings.bot_username, "| webhook:", settings.webhook_url or "(base url not set)")
```

### 6.1 `tgram_setup_bot.py` (from `tgram_starter/notebook_setup_bot.py`)

Header markdown: "Run once per environment or URL change. This hits the REAL Bot API. **The dev bot is shared with
`tgram_starter`** (D8): whichever webhook you set last receives every update."

| Cell | Source in starter | Change |
|---|---|---|
| 1 Setup | cell 1 (lines 15–28) | Use the shared cell above. Optionally `BOT_KEY = "rest_admin"` for when the rider bot exists. |
| 2 Validate token | cell 2 (lines 30–34) | Same. Compare `me.username` with `settings.bot_username`. |
| 3 Current webhook (read-only) | cell 3 (lines 36–40) | Same. |
| 4 **Set webhook** | cell 4 (lines 42–55) | `dp = build_rest_admin_dispatcher(settings)` from `channels.telegram.bots`. `url = settings.webhook_url` (assert it starts with `https://`). `secret_token=settings.webhook_secret.get_secret_value()`. `allowed_updates=dp.resolve_used_update_types()`. `drop_pending_updates=False`. Drop the hard-coded URL. |
| 5 Verify | cell 5 (lines 57–63) | Same; assert `info.url == settings.webhook_url`. |
| 6 Command menu | cell 6 (lines 65–77) | `await bot.set_my_commands(REST_ADMIN_COMMANDS)` from `channels.telegram.rest_admin.commands`. |
| 7 Smoke test | cell 7 (lines 125–131) | `GET {base}/docs` or an existing health route, then `POST settings.webhook_url` with a wrong secret and expect **403**. (OrdeloAgent has no `/health`; pick an existing GET or accept any 2xx/404 for the first call.) |
| 8 **Hand the bot back to the starter** | new | Commented out by default: `await bot.set_webhook(url=STARTER_URL + "/telegram/webhook", secret_token=<starter secret from tgram_starter/.env>, ...)`. Explain that this stops the service receiving updates. |
| 9 Delete webhook | cell 8 (lines 133–135) | Same; stays commented. |
| 10 Cleanup | cell 9 (line 138) | `await bot.session.close()`. |

Drop the starter's cells 6a, 6b and 6c (Mini App preflight, menu button and launch button).

### 6.2 `tgram_scratchpad.py` (from `tgram_starter/notebook.py`)

Keep, adapted to the shared setup cell:
- Who am I (`bot.get_me()`).
- `CHAT_ID = None  # set your numeric Telegram id (send /whoami to the bot)` followed by an assert. There's no
  admin-ID fallback (D3a).
- Plain and formatted send, reply, edit and delete (starter cells 4, 5 and 5a).
- Draft streaming with `send_message_draft` (starter cell 5b).
- Live tracker edited in place, with `TelegramRetryAfter` backoff (starter cell 5c).
- Any later starter cells that only use `bot` and `CHAT_ID`.

Drop the `order_offer` import and cell, anything calling the starter's HTTP endpoints (`/invites` and `/send`), and
anything Mini App related. Fix the starter's leftover bugs while copying: cell 5a prints `ok` while the delete line is
commented out, and the hard-coded `CHAT_ID = -1004443870717` overrides the default.

---

## 7. Tests

The global `tests/conftest.py` fakes `aws_setting` before any import (`_install_fake_aws_setting`, lines 100–129) using
`_STUB_AGENT_ENV` (lines 53–98). Add:

```python
    # Telegram (restaurant-admin bot)
    "tgram_rest_admin_bot_token": "123456:TEST-token",
    "tgram_rest_admin_bot_username": "test_rest_admin_bot",
    "tgram_rest_admin_webhook_secret": "test-tgram-secret",
    "tgram_rest_admin_webhook_base_url": "https://test.example.com",
```

These keys make `rest_admin_bot` a real `Bot` in tests. No network is used because nothing calls the API during import.

### 7.1 `tests/channels/telegram/conftest.py`: offline Bot API recorder

```python
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Message


class RecordingSession(BaseSession):
    """Captures outgoing Bot API calls; returns minimal valid results. No network."""

    def __init__(self):
        super().__init__()
        self.calls: list = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message.model_validate(
                {"message_id": len(self.calls), "date": 0,
                 "chat": {"id": method.chat_id, "type": "private"}, "text": method.text},
                context={"bot": bot},
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        if False:
            yield b""


@pytest.fixture
def recording_bot():
    session = RecordingSession()
    return Bot(token="123456:TEST-token", session=session), session


def message_update(text: str, user_id: int = 111, update_id: int = 1) -> dict:
    cmd_len = len(text.split()[0]) if text.startswith("/") else 0
    return {
        "update_id": update_id,
        "message": {
            "message_id": 10, "date": 1_700_000_000,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Ada", "username": "ada"},
            "text": text,
            **({"entities": [{"type": "bot_command", "offset": 0, "length": cmd_len}]} if cmd_len else {}),
        },
    }
```

### 7.2 Test cases

`tests/config/test_tgram_setting.py`
- `for_bot("rest_admin", env)` reads the prefixed keys, ignores `tgram_rider_*` and unrelated keys, strips `@` from
  the username and `/` from the base URL.
- `enabled` is false when the token or secret is missing or `""`. `build_bot` then returns `None` without raising.
- A malformed token (`"not-a-token"`) gives `build_bot` → `None`.
- An invalid webhook secret (`"has space"`) raises `ValidationError`.
- `webhook_path == "/telegram/rest-admin/webhook"`. `webhook_url` is `""` when no base URL is set.
- `repr(settings)` doesn't contain the token or secret.

`tests/channels/telegram/test_bots.py`
- `build_rest_admin_dispatcher` called twice gives **two different routers**, and building both Dispatchers raises
  nothing. This is the regression guard for the starter's `_dp` singleton problem.
- `build_registry([(settings, None)]) == {}`. With a bot, the key is `"rest_admin"`.
  `find_by_slug(registry, "rest-admin")` finds it, and `find_by_slug(registry, "rider")` is `None`.
- `close_registry` closes each session (use a `RecordingSession` or a mock and assert the call).

`tests/channels/telegram/test_rest_admin_router.py` (feed updates with `await dp.feed_update(bot, Update.model_validate(...))`)
- `/start` → one `SendMessage` whose text contains "isn't linked".
- `/help` → text lists `/start`, `/help` and `/whoami`, and **no** starter commands (`/menu`, `/invite`, `/app`).
- `/whoami` → contains `from_user.id` `111` and "not linked". A username with `<b>` is escaped.
- Free text → the fallback reply.

`tests/watomation/routers/test_telegram_webhook.py`: build a **small** FastAPI app containing only
`telegram_webhook.router`, and set `app.state.telegram_bots` to a registry built from a `recording_bot`. Don't
import `fapp_ordelo_agent` here; it pulls in the whole app.
- Unknown slug → 404. An empty registry (bot disabled) → 404.
- Missing or wrong secret → 403. A non-ASCII header doesn't raise.
- Valid secret with `/start` → 200, and the session recorded one `SendMessage`.
- Valid secret with `{"update_id": 5, "message": "garbage"}` → 200 and a warning logged.
- A handler that raises (monkeypatch `tg.dp.feed_update` to raise) → 200 and an exception logged.
- `HANDLER_TIMEOUT_SECS` reached (monkeypatch it to `0.01` and use a slow `feed_update`) → 200.

`tests/test_smoke_imports.py`: add `"config.tgram_setting"`, `"channels.telegram.bots"`,
`"channels.telegram.rest_admin.router"` and `"watomation.routers.telegram_webhook"` to the parametrised list
(around lines 22–60).

Commands: `pytest tests/config tests/channels tests/watomation/routers/test_telegram_webhook.py tests/test_smoke_imports.py`,
then `pytest` and `ruff check .`. The starter's own tests (`tgram_starter/tests/`) aren't part of the main run.
`[tool.pytest.ini_options].testpaths = ["tests"]` already excludes them.

---

## 8. Documentation edits (in the same change)

**ADR 0011** (`docs/adr/0011-...md`). Add a dated "Amendment — 15 Oct 2026 (step-1 scaffold)" section rather
than rewriting the text:
1. The settings file is `config/tgram_setting.py` (not `telegram_setting.py`). Keys are `tgram_<bot_key>_*`, optional,
   and a bot is enabled only when its token and secret are present.
2. The restaurant-admin bot key is `rest_admin` and its route is `/telegram/rest-admin/webhook`.
3. "Startup construction must become explicit": aiogram `Bot` objects are built when `config` is imported, because
   building one opens no connection and the pattern matches `_async_wa_client`. Dispatchers and routers are built in
   the FastAPI lifespan through `channels/telegram/bots.py`, and sessions close on shutdown.
4. Restaurant-admin identity: link by shared contact (`contact.user_id == from_user.id`), with the phone checked
   against `restaurant_master.admins`. Restaurant-admin onboarding doesn't use invites.
5. Step 1 handles updates inline without an inbox. The inbox stays a gate before any action that changes state.
6. Test environment: the starter's dev bot doubles as the restaurant-admin test bot until a dedicated bot is created.

**CONTEXT.md**: add two short entries in the existing style:
- **Restaurant-admin bot**: the Telegram bot (`bot_key=rest_admin`) that restaurant admins use for order actions
  and notifications. It is deterministic and never runs a LangGraph agent. It sits alongside WhatsApp; it is not a
  customer channel.
- **Telegram identity**: the link from a Telegram account (`telegram_user_id`, `chat_id`) to an Ordelo principal. For
  restaurant admins that principal is a phone number in `restaurant_master.admins`. A Telegram identity only
  authenticates; restaurant membership is still checked on every action.

**docs/local-testing-runbook.md**: add a short "Telegram restaurant-admin bot" section after §4 (tunnel):
point the dev bot's webhook at `<tunnel>/telegram/rest-admin/webhook` with `notebooks/telegram/tgram_setup_bot.py`
cell 4, restore it with the same cell using the test or prod base URL, and warn that the bot is shared with
`tgram_starter`.

---

## 9. Next step: restaurant-admin linking

> **Superseded 15 Oct 2026.** Linking was built as an invite flow (`t_invites`, `/start <code>` with a
> confirmation tap) and the contact-share design below was dropped. See the "Restaurant-admin identity (revised)"
> bullet in the ADR 0011 amendment, `ordelo_datamodels/migrations/create_t_invites.sql` and
> `channels/telegram/invites.py`. The text below is kept for history.

This is here so the scaffold doesn't paint itself into a corner:
1. `/start` (not linked) → reply with `contact_request_kb()` (already in `channels/telegram/keyboards.py`).
2. `F.contact` handler: reject if `contact.user_id != from_user.id` (same check as
   `tgram_starter/handlers/onboarding.py:52-58`). Normalise the phone to digits only, which is how `rider_id` and
   admins are stored today.
3. Look for that phone in `restaurant_master.admins` across restaurants. Supabase REST is **synchronous**, so wrap it
   in `asyncio.to_thread()` (CLAUDE.md rule). If there's no match → "Number not registered with any restaurant".
4. Upsert `telegram_identities(bot_key, telegram_user_id, telegram_chat_id, phone, username_snapshot, linked_at,
   revoked_at)` with a unique `(bot_key, telegram_user_id)` constraint. New migration in
   `ordelo_datamodels/migrations/`.
5. Authorise every action by re-checking `restaurant_master.admins` (removing the phone revokes access) and never
   trusting `chat_id` or callback data alone (ADR 0011 decision 5).
6. Before the **first action that changes state** (order accept, pickup time, ready): build `telegram_inbox`
   (persist and deduplicate `(bot_key, update_id)` before replying 200, then claim and complete through a recoverable
   worker) per ADR 0011 "Acknowledgement and durable work".

---

## 10. Operator steps (manual; the implementing agent must not do these)

1. Generate a new webhook secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Add the four `tgram_rest_admin_*` keys (§3) to the AWS secret that the **test** deployment loads, using
   `upload_secrets.sh` or the `aws secretsmanager update-secret` recipe in the `aws_setting.py` docstring. Use the
   starter bot's token and username (D8).
   - **Open check:** `aws_setting.py:108` hard-codes `ordelo-agent-env`. If test and prod read the same secret, prod
     also gets the dev bot token. That's harmless while the webhook points at the test URL, but decide before the
     production bot exists. A separate secret or a deploy-time `secret_name` may be needed.
3. Deploy to test, then run `notebooks/telegram/tgram_setup_bot.py` cells 1–7.
4. In Telegram, send `/start`, `/help` and `/whoami` to the bot and check the replies.
5. To use the starter again, run cell 8 (hand the bot back) and reverse it afterwards.

---

## 11. Implementation order and acceptance checklist

1. [ ] `pyproject.toml` + `uv lock` + `uv sync`. Confirm `python -c "import aiogram; print(aiogram.__version__)"` prints `3.31.0`.
2. [ ] `config/tgram_setting.py` and the `config/__init__.py` exports. Write `tests/config/test_tgram_setting.py` first (TDD).
3. [ ] `tests/conftest.py` stub keys, then add the smoke-import entries.
4. [ ] `channels/telegram/{errors,keyboards,callbacks}.py`, `rest_admin/{commands,router}.py`, `bots.py`, with the router and bots tests.
5. [ ] `watomation/routers/telegram_webhook.py` and its tests. Then edit `fapp_ordelo_agent.py` (lifespan + `include_router`).
6. [ ] `uv run watomation/fapp_ordelo_agent.py` locally with **no** Telegram keys: the app starts, logs
       `telegram[rest_admin]: disabled`, and `POST /telegram/rest-admin/webhook` returns 404. WhatsApp routes work as before.
7. [ ] Same run with the keys exported as `TGRAM_REST_ADMIN_*` env vars: a curl with the wrong secret gets 403, and a
       curl with the right secret and a `/help` update gets 200 (send it to your own chat id, or check that the
       handler ran and failed on the network with the error logged).
8. [ ] The two notebooks; run cells 1–3 against the dev bot (read-only).
9. [ ] Doc edits (§8).
10. [ ] `pytest`, then `ruff check .`, then `git diff --stat -- tgram_starter/` shows **no changes**.

**Done when:** all tests pass, the app starts with and without Telegram keys, the dev bot answers `/start`, `/help`
and `/whoami` through the test deployment, `tgram_starter/` is byte-for-byte unchanged, and nothing in production
code imports `tgram_starter`.
