# Telegram layer — how OrdeloAgent talks to Telegram

Living document: **add to it every time the Telegram layer changes** (see [Change log](#change-log)). Companion: [interactive guide](telegram-layer.html) (same content, with a clickable request flow, file map and DB-to-code cross-reference). Decisions: [ADR 0011](adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) and its 15 October 2026 amendment. Original plan: [plans/telegram-rest-admin-scaffold-plan.md](../plans/telegram-rest-admin-scaffold-plan.md). Vocabulary: [CONTEXT.md](../CONTEXT.md) ("Restaurant-admin bot", "Telegram invite", "Telegram identity").

Last reviewed: 15 October 2026. This is a code review, not a live audit of Telegram, Supabase or AWS.

## 1. What it is

OrdeloAgent's existing FastAPI service also receives Telegram webhooks. One **bot** per audience (today only the restaurant-admin bot, key `rest_admin`; a rider bot is planned) shares one set of building blocks:

- **Settings** per bot, from the AWS secret, built once at import (`config/tgram_setting.py`). Token and webhook secret are **required**: the service refuses to start without them.
- **Registry** of bots (`channels/telegram/bots.py`), each with its own aiogram `Bot` and its own `Dispatcher` and router tree.
- **One thin webhook route** (`watomation/routers/telegram_webhook.py`): checks the secret header, feeds the update to the right bot's dispatcher, always answers 200.
- **Deterministic handlers** (`channels/telegram/rest_admin/router.py`): commands and buttons, no LangGraph agent.
- **Database-backed logic behind RPCs** (`channels/telegram/invites.py` calls functions defined in `ordelo_datamodels/migrations/create_t_invites.sql`). See [section 5](#5-the-design-pattern-to-reuse-rpc-owns-the-logic-one-python-wrapper-per-domain).

`tgram_starter/` (the standalone starter kit) is kept unchanged for later reference. Nothing imports it.

## 2. Request flow (a restaurant admin taps an invite link)

```
Telegram ──POST /telegram/rest-admin/webhook──▶ Cloudflare tunnel / load balancer ──▶ FastAPI
  watomation/routers/telegram_webhook.py
    1. find the bot by URL slug            channels/telegram/bots.py  find_by_slug()
    2. compare X-Telegram-Bot-Api-Secret-Token (constant time)       403 if wrong, 404 if no such bot
    3. validate the Update; log delivery_lag; run the handler with a 25 s timeout
    4. dp.feed_update(bot, update)         aiogram Dispatcher for THIS bot only
         channels/telegram/rest_admin/router.py
           /start <code>   → invites.preview_invite()  → RPC t_invite_preview   → "Link this chat to <b>name</b>?" [Yes][No]
           tap Yes         → invites.claim_invite()    → RPC t_claim_invite     → "You've been onboarded successfully."
           /start, /whoami → invites.linked_restaurants() → RPC t_linked_restaurants
    5. always return {"ok": true}          Telegram retries non-2xx, so failures are logged, not raised
```

The webhook route does not contain business logic. Per-bot objects are created in the FastAPI lifespan (`watomation/fapp_ordelo_agent.py`: `app.state.telegram_bots = default_registry()`, `close_registry()` on shutdown). The app **never** calls `set_webhook` or `delete_webhook`; that is an explicit operator step (notebook cell 4).

## 3. File map

| Area | File | What it does |
|---|---|---|
| Settings | `config/tgram_setting.py` | `TgramBotSettings.for_bot("rest_admin", agent_env)` reads `tgram_rest_admin_*` keys; `build_bot()`; module values `tgram_rest_admin_settings`, `rest_admin_bot` (re-exported from `config/__init__.py`) |
| DB clients | `config/pg_setting.py` | `client_ordelo` (anon key) and `client_ordelo_service` (service-role key, used by `invites.py`) |
| Registry | `channels/telegram/bots.py` | `TelegramBot` (settings + bot + dispatcher), `build_registry`, `default_registry`, `find_by_slug`, `close_registry`, `DISPATCHER_FACTORIES` (one factory per bot key) |
| Errors | `channels/telegram/errors.py` | Dispatcher error handlers (ignores stale/too-old callback queries) |
| Callback data | `channels/telegram/callbacks.py` | `InviteDecision` (`inv:<code>:y\|n`), the 64-byte limit check |
| Keyboards | `channels/telegram/keyboards.py` | `invite_confirm_kb(code)`; `contact_request_kb()` (unused for now, kept for the later phone-verified flow) |
| **DB access** | `channels/telegram/invites.py` | `preview_invite`, `claim_invite`, `linked_restaurants`: thin async wrappers over the three RPCs |
| Restaurant-admin bot | `channels/telegram/rest_admin/router.py` | `build_router()` returns a NEW router per call; `/start`, `/help`, `/whoami`, the Yes/No callback, a text fallback |
| | `channels/telegram/rest_admin/commands.py` | command menu and help text |
| Webhook | `watomation/routers/telegram_webhook.py` | `POST /telegram/{bot_slug}/webhook` |
| App wiring | `watomation/fapp_ordelo_agent.py` | lifespan builds and closes the registry; `include_router(telegram_webhook.router)` |
| **Database** | `ordelo_datamodels/migrations/create_t_invites.sql` | `t_invites` table, `t_invites_shareable` view, the three RPC functions, grants, operator SQL. **The one place that defines the invite database objects** |
| | `ordelo_datamodels/migrations/drop_tgram_invites.sql` | cleanup of the old `tgram_` names (run once before the `t_` migration) |
| Operations | `notebooks/telegram/tgram_setup_bot.py` | token check, set/verify webhook (`allowed_updates` computed from the handlers), set command menu, smoke tests |
| | `notebooks/telegram/tgram_scratchpad.py` | send/edit/reply experiments |
| Tests | `tests/config/test_tgram_setting.py` | settings, fail-fast, secret hygiene |
| | `tests/channels/telegram/` | `conftest.py` (RecordingSession, `FakeInviteDb` that mimics the RPC contract), `test_bots.py`, `test_invites.py`, `test_rest_admin_router.py` |
| | `tests/watomation/routers/test_telegram_webhook.py` | 404 / 403 / invalid update / handler failure still 200 |
| Docs | `docs/adr/0011-...md`, `docs/local-testing-runbook.md` (Telegram section), `CONTEXT.md`, `.claude/skills/database-operations/SKILL.md` (invite SOP) | decisions, local setup, vocabulary, operator procedure |

## 4. Settings, secrets and clients

- **Keys** in the AWS secret `ordelo-agent-env`: `tgram_rest_admin_bot_token`, `tgram_rest_admin_webhook_secret` (**required**), `tgram_rest_admin_bot_username`, `tgram_rest_admin_webhook_base_url` (optional; the latter is used only by the setup notebook). Local `TGRAM_REST_ADMIN_*` environment variables fill gaps.
- **Fail fast:** a missing or malformed token or webhook secret raises `RuntimeError` when `config` is imported, naming the keys (never their values).
- **One webhook per bot token.** A bot token that is shared with another service (for example `tgram_starter`) delivers every update to whichever URL was set last.
- **Invite links** use the bot username stored in the database row `ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME`, not the AWS key. Changing bots means changing that row **and** re-running the webhook notebook cell.
- **Which Supabase client:** `invites.py` uses `client_ordelo_service`, because the RPCs and the table are service-role only. The anon `client_ordelo` is denied (permission error on the functions, RLS on the table).

## 5. The design pattern to reuse: RPC owns the logic, one Python wrapper per domain

This is the pattern to copy for new Telegram features (and other database-backed features).

**The shape**

1. The rule lives in **one Postgres function** (RPC). Example: `t_claim_invite(...)` decides, in one atomic conditional `UPDATE`, who wins an invite, checks expiry and status, and handles the "already linked" race. It returns a small `jsonb` object with a `result` discriminator (`ok`, `expired`, `revoked`, ...).
2. The function is defined **in the same migration file as the table it works on** (`create_t_invites.sql` holds `t_invites`, the view, and all three RPCs, plus grants and operator SQL).
3. **One Python module per domain** (`channels/telegram/invites.py`) wraps each RPC in a typed `async def` (`claim_invite`, `preview_invite`, `linked_restaurants`). It runs the synchronous Supabase call in `asyncio.to_thread`, validates the response shape, and returns a small dataclass (`InviteOutcome`).
4. Handlers (`rest_admin/router.py`) call the wrapper only. They never build queries, never touch the table, and never re-implement the rule.

**Why it is good**

- Atomic and race-safe in the database, so three gunicorn workers and Telegram retries cannot double-claim.
- One definition of the rule. The Python is a thin adapter, easy to read and to fake in tests.
- Permissions are simple: the table and functions are locked to the service role.
- The bot code and the operator (SQL editor, agents) use the same objects.

**The cross-reference rule (every time)**

| Where | Must name |
|---|---|
| Module docstring of the Python wrapper (`invites.py`) | the SQL file that defines the RPCs, and for each Python function the RPC it calls |
| Header of the SQL migration (`create_t_invites.sql`) | the Python module and functions that call each RPC, and the other tables it touches |
| This document, section 6 | the full table: database object, defining file, Python caller, tests |

When you add, rename or change an RPC, update **all three** in the same change.

**Checklist: adding a new database-backed Telegram feature**

1. Add the table (if any) and its RPC(s) to a migration file in `ordelo_datamodels/migrations/` (extend the existing file for the same domain). Write the header: what it adds, how it fits with other tables, lifecycle, security, not-yet-done.
2. `REVOKE ALL ... FROM PUBLIC, anon, authenticated` on the functions and view, enable RLS on the table. Return `jsonb` with a `result` string.
3. Add one wrapper function per RPC in the domain's Python module. Use `client_ordelo_service`, `asyncio.to_thread`, a typed outcome. Update its module docstring (RPC names and the SQL file).
4. Update the SQL header's "Python callers" list.
5. Extend the test fake (`FakeInviteDb` mimics the RPC contract) and add tests for each `result` value.
6. Add a row to the cross-reference table below and an entry to the [change log](#change-log).
7. Apply the migration in Supabase **before** deploying the code that calls it.

## 6. Cross-reference: database object ↔ code ↔ tests

| Database object | Defined in | Python caller | Used by handler | Tests |
|---|---|---|---|---|
| table `t_invites` | `create_t_invites.sql` | none directly (only through the RPCs) | n/a | `FakeInviteDb` mimics it |
| view `t_invites_shareable` | `create_t_invites.sql` | none (operator SQL and agents only) | n/a | n/a |
| function `t_new_invite_code()` | `create_t_invites.sql` | none (column default) | n/a | n/a |
| trigger function `t_invites_normalize_phone()` | `create_t_invites.sql` | none (trigger) | n/a | n/a |
| RPC `t_invite_preview(p_code, p_bot_key, p_user_id)` | `create_t_invites.sql` | `invites.preview_invite` | `/start <code>` | `test_invites.py`, `test_rest_admin_router.py` |
| RPC `t_claim_invite(...)` | `create_t_invites.sql` | `invites.claim_invite` | Yes button | `test_invites.py`, `test_rest_admin_router.py` |
| RPC `t_linked_restaurants(p_bot_key, p_user_id)` | `create_t_invites.sql` | `invites.linked_restaurants` | `/start`, `/whoami` | `test_invites.py`, `test_rest_admin_router.py` |
| config row `ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME` | operator SQL (runbook) | none (read by the view) | n/a | n/a |
| existing table `restaurant_master` | existing migrations | none (joined inside the RPCs for the restaurant name) | n/a | n/a |

## 7. Invite lifecycle and operations

`pending → claimed` (person confirms before `expires_at`), `pending → expired` (computed when `expires_at` passes), `pending|claimed → revoked` (operator). There is no way back to `pending`; issue a new invite. A claim records `telegram_user_id`, `telegram_chat_id`, username and first name. `phone_verified` is reserved for a later flow and is never set today.

Operators (and agents) create invites, read the link from `t_invites_shareable`, see who claimed what, and revoke, using the SQL in the footer of `create_t_invites.sql` and the **Telegram Invites** section of the [database-operations skill](../.claude/skills/database-operations/SKILL.md). Deleting rows needs explicit approval; revoke instead.

Setup for a new bot or environment: add the AWS keys, set the `ordelo_config` username row, restart, run notebook cell 4 to set the webhook, then send `/start` with an invite link. Details in the [local testing runbook](local-testing-runbook.md).

## 8. Testing

- `tests/conftest.py` stubs the AWS secret (including the `tgram_rest_admin_*` keys), so `import config` works in tests.
- Handlers are tested through a real aiogram `Dispatcher` with a `RecordingSession` (no network); the database is replaced by `FakeInviteDb`, which mimics the three RPCs' return shapes. If an RPC's contract changes, change the fake in the same commit.
- The webhook tests cover 404 (unknown bot), 403 (bad or missing secret), invalid updates, and handler failure still returning 200.
- Nothing here proves the SQL itself: it has been parsed, and exercised live for `t_invite_preview` and the insert path, but the full claim path needs a real tap in Telegram.

## 9. Not done yet

- **Durable inbox** (`(bot_key, update_id)` dedupe) before any state-changing handler. Today the route processes inline.
- **Order actions** (accept, pickup time, ready) must re-check that the person's invite is still `claimed` for that restaurant, and a decision is pending on whether the phone must also be in `restaurant_master.admins`.
- **Rider bot** (`DISPATCHER_FACTORIES` is ready for a second key) and the **phone-verified** contact flow.

## Change log

Add one line per change, newest first: date, what changed, files.

- 2026-10-15: Telegram layer scaffold: settings (fail-fast), registry, webhook route, restaurant-admin bot, invite flow (`t_invites`, three RPCs, `invites.py`), service-role client, delivery-lag logging, notebooks, tests, docs. Renamed `tgram_*` database objects to `t_*` (run `drop_tgram_invites.sql`, then `create_t_invites.sql`).
