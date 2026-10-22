# Telegram layer — how OrdeloAgent talks to Telegram

Living document: **add to it every time the Telegram layer changes** (see [Change log](#change-log)). Companion: [interactive guide](telegram-layer.html) (same content, with a clickable request flow, file map and DB-to-code cross-reference). Decisions: [ADR 0011](adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md) and its 15 October 2026 amendment. Plan: [plans/telegram-rest-admin-scaffold-plan.md](../plans/telegram-rest-admin-scaffold-plan.md). Vocabulary: [CONTEXT.md](../CONTEXT.md) ("Restaurant-admin bot", "Telegram invite", "Telegram identity").

Last reviewed: 15 October 2026. This is a code review, not a live audit of Telegram, Supabase or AWS.

## 1. What it is

OrdeloAgent's existing FastAPI service also receives Telegram webhooks. One **bot** per audience (today only the restaurant-admin bot, key `rest_admin`; a rider bot is planned) shares one set of building blocks:

- **Settings** per bot, from the AWS secret, built once at import (`config/tgram_setting.py`). Token and webhook secret are **required**: the service refuses to start without them.
- **Registry** of bots (`channels/telegram/bots.py`), each with its own aiogram `Bot` and its own `Dispatcher` and router tree.
- **One thin webhook route** (`watomation/routers/telegram_webhook.py`): checks the secret header, feeds the update to the right bot's dispatcher, always answers 200.
- **Deterministic handlers** (`channels/telegram/rest_admin/router.py`): commands and buttons, no LangGraph agent.
- **Database-backed logic behind RPCs** (`channels/telegram/invites.py` calls functions defined in `ordelo_datamodels/telegram/t_invites.sql`). See [section 5](#5-the-design-pattern-to-reuse-rpc-owns-the-logic-one-python-wrapper-per-domain).

`tgram_starter/` (the standalone starter kit) is kept unchanged for later reference. Nothing imports it.

## 2. Request flow (a restaurant admin taps an invite link)

```
Telegram ──POST /telegram/rest-admin/webhook──▶ Cloudflare tunnel / load balancer ──▶ FastAPI
  watomation/routers/telegram_webhook.py
    1. find the bot by URL slug            channels/telegram/bots.py  find_by_slug()
    2. compare X-Telegram-Bot-Api-Secret-Token (constant time)       403 if wrong, 404 if no such bot
    3. validate the Update, answer 200 at once, and run the handler (25 s timeout) in a BackgroundTask so a slow Telegram call cannot stall the bot's later updates; updates may now run concurrently
    4. dp.feed_update(bot, update)         aiogram Dispatcher for THIS bot only
         channels/telegram/inbox.py  InboxMiddleware (outer middleware on dp.update)
           claim → RPC t_inbox_claim   'new' → run the handlers; 'duplicate' → skip (Telegram retry)
           after the handlers: RPC t_inbox_finish → row 'done' or 'failed'  (inbox down → fail OPEN, log, handle anyway)
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
| Registry | `channels/telegram/bots.py` | `TelegramBot` (settings + bot + dispatcher + `cards`), `build_registry`, `default_registry`, `find_by_slug`, `close_registry`, `DISPATCHER_FACTORIES` (one factory per bot key) |
| Errors | `channels/telegram/errors.py` | Dispatcher error handlers (ignores stale/too-old callback queries) |
| Callback data | `channels/telegram/callbacks.py` | `InviteDecision` (`inv:<code>:y\|n`), `OrderAction` (`ord:<order>:d\|t:acc\|dec\|pk:<minutes>`), the 64-byte limit check |
| Keyboards | `channels/telegram/keyboards.py` | `invite_confirm_kb(code)`; `contact_request_kb()` (unused for now, kept for the later phone-verified flow) |
| Decision rule (shared) | `utils_common/order_management/restaurant_decision.py` | `decide`, `set_pickup`, `describe`: thin wrappers over `restaurant_order_decide` / `restaurant_order_set_pickup`. Used by the WhatsApp handlers; Telegram reaches the same SQL through `t_order_decide` / `t_order_set_pickup` (`CardStore.decide` / `set_pickup`) |
| Inbox | `channels/telegram/inbox.py` | `claim`, `finish` (thin wrappers over `t_inbox_claim` / `t_inbox_finish`) and `InboxMiddleware(bot_key)`, registered once per bot in `bots.py`: at-most-once handling per `(bot_key, update_id)` |
| Order cards | `channels/telegram/rest_admin/order_cards/` | `OrderCards(bot, bot_key)` with `remind(order, n, of)`, `refresh(order)` and `tap(query, action)`; public names `OrderCards`, `OrderRef`. `model.py` is pure (immutable `Card` changed by events, every text, button and toast), `store.py` (`CardStore`: the RPCs), `io.py` (`TelegramIO`: send / edit / delete and Telegram error mapping) |
| Order buttons | `channels/telegram/rest_admin/orders.py` | `build_orders_router()`: ONE handler, `OrderAction.filter()` → `order_cards.tap(query, callback_data)`; included by `router.build_router()`; `order_cards` is injected from `dp["order_cards"]` |
| Scratchpad | `channels/telegram/rest_admin/scratchpad.py` | Removable `/scratchpad` menu with 27 private-chat examples, including a Salisbury Mini App launcher, structured receipts, coloured/disabled actions, expandable progress and embedded pickup controls. Mounted before the main router in `bots.py`; no business RPCs. |
| Kitchen receipts | `channels/telegram/rest_admin/receipts/` | `Receipts(bot, bot_key)` with `send(order, dispatch_id)`, `refresh(order)` and `tap(query, action)` (Ready / +10 / +20). `model.py` is pure (`Receipt`, `view(viewer)`, toasts, status keys), `store.py` (`ReceiptStore`: the RPCs); sending and editing reuse `order_cards/io.TelegramIO` |
| Plain notices | `channels/telegram/rest_admin/notices.py` | `Notices.send(rest_ref, text_html, notice=, order=, reply_to=)`: auto-accepted, rider alert, delivered, feedback. Destinations and reply target from `t_notice_targets`, audit row from `t_notice_sent`; never raises, each chat isolated |
| Notifier (both channels) | `utils_common/notify/restaurant_notifier.py` | `notify(notice)` sends a restaurant-facing notice to WhatsApp (the unchanged `wa_senders` call) and Telegram at once; `KitchenReceipt`, `TakeawayReceipt`, `AutoAccepted`, `RiderAlert`, `DeliveryCompleted`, `Feedback`; never raises; test seam `use_adapters` |
| Kitchen actions (shared) | `utils_common/order_management/restaurant_actions.py` | `ready`, `adjust_pickup`: thin wrappers over `restaurant_order_ready` / `restaurant_order_adjust_pickup` (WhatsApp) and `t_order_ready` / `t_order_adjust_pickup` (Telegram); the rider / customer follow-up runs only on `ok` |
| Order alerts route | `watomation/routers/telegram_order_alerts.py` | `POST /telegram/rest-admin/order-alerts`, called by `job_t_order_alerts()` and `job_t_receipt_refresh()`: 503 without a bot (checkpoints stay pending), otherwise 200 and background `remind` / `refresh` (cards) and receipt `refresh` |
| **DB access** | `channels/telegram/invites.py` | `preview_invite`, `claim_invite`, `linked_restaurants`: thin async wrappers over the three RPCs |
| Restaurant-admin bot | `channels/telegram/rest_admin/router.py` | `build_router()` returns a NEW router per call; `/start`, `/help`, `/whoami`, the Yes/No callback, a text fallback |
| | `channels/telegram/rest_admin/commands.py` | command menu and help text |
| Webhook | `watomation/routers/telegram_webhook.py` | `POST /telegram/{bot_slug}/webhook` |
| App wiring | `watomation/fapp_ordelo_agent.py` | lifespan builds and closes the registry; `include_router(telegram_webhook.router)` |
| **Database** | `ordelo_datamodels/telegram/t_invites.sql` | `t_invites` table, `t_invites_shareable` view, the three RPC functions, grants, operator SQL. **The one place that defines the invite database objects** |
| | `ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql` | `delivery_summary_status_check` now allows `'declined'` (R1-a), `restaurant_admin_label`, `restaurant_order_decide`, `restaurant_order_set_pickup`, and the Telegram wrappers `t_order_admin_phone`, `t_order_decide`, `t_order_set_pickup` (D14 authorisation) |
| | `ordelo_datamodels/telegram/t_inbox.sql` | `t_inbox` table, `t_inbox_claim`, `t_inbox_finish`, grants |
| | `ordelo_datamodels/telegram/t_order_alerts.sql` | `t_order_alerts` (schedule), `t_sent_messages` (ledger), the card functions, `job_t_order_alerts()` (the 5 s sweep), `t_housekeeping()`, config rows, operator `cron.schedule` lines |
| | `ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql` | Phases 7-8: Ready / adjust-pickup columns on the summaries, the shared RPCs `restaurant_order_ready` / `restaurant_order_adjust_pickup`, their `t_` wrappers, the receipt functions (`t_receipt_status`, `t_receipt_snapshot`, `t_receipt_sent`, `t_receipts_stale`, `t_receipts_take`), the notice functions (`t_notice_targets`, `t_notice_sent`) and `job_t_receipt_refresh()` (the second 5 s sweep) |
| | `ordelo_datamodels/test_support/test_restaurant_notices.sql` | fake-row script for the live check: `STRK-TEST-*` orders in town `dummy`, one stage per notice; guide: `docs/live-order-test-harness.md` |
| | `ordelo_datamodels/migrations/drop_tgram_invites.sql` | cleanup of the old `tgram_` names (run once before the `t_` migration) |
| Operations | `notebooks/telegram/tgram_setup_bot.py` | select `BOT_KEY` in the first cell (`rest_admin` or `rider`); token check, set/verify the selected webhook (`allowed_updates` from its handlers), set its command menu, smoke tests |
| | `notebooks/telegram/tgram_scratchpad.py` | select `BOT_KEY` in the first cell; send/edit/reply experiments (rich text button demo is restaurant-admin only) |
| Tests | `tests/config/test_tgram_setting.py` | settings, fail-fast, secret hygiene |
| | `tests/channels/telegram/` | `conftest.py` (RecordingSession, `FakeInviteDb` that mimics the RPC contract), `test_bots.py`, `test_invites.py`, `test_rest_admin_router.py` |
| | `tests/channels/telegram/test_inbox.py` | `FakeInboxDb` (conftest) mimics the inbox RPCs: duplicate skipped, failed/cancelled handler recorded, fail-open |
| | `tests/channels/telegram/test_order_card_model.py`, `test_order_cards.py` | the pure card model (transitions, views per viewer, toasts) and `remind` / `refresh` against `FakeCardStore` (conftest, mimics the card RPCs) + `RecordingSession` |
| | `tests/channels/telegram/test_order_taps.py`, `test_order_card_store.py` | taps through a real `Dispatcher` (accept / decline / pickup / refused / revoked / group-shaped / duplicate delivery) and the `CardStore` RPC contract |
| | `tests/watomation/routers/test_telegram_order_alerts.py` | 503 without a bot, background calls, payload validation |
| | `tests/channels/telegram/test_receipt_model.py`, `test_receipts.py`, `test_notices.py`, `fake_receipt_store.py` | the pure receipt (text, buttons, 4096 cut), receipt taps through a real `Dispatcher` against `FakeActionsDb` (WhatsApp vs Telegram race), and plain notices (reply targets, isolation, audit) |
| | `tests/utils_common/test_restaurant_notifier.py`, `tests/utils_common/order_management/` | the notifier (both channels, one failing alone, the exact WhatsApp calls) and `restaurant_actions` against `FakeActionsDb` (`tests/fixtures/fake_restaurant_actions.py`) |
| | `tests/sql/test_restaurant_ready_adjust_notices_sql.py`, `test_restaurant_notices_script_sql.py` | the migration (first Ready wins, +N relative to the original pickup, status keys, destinations, races) and the fake-row script, in the isolated database |
| | `tests/sql/` | isolated-database tests of the migrations (skipped without `ORDELO_TEST_DB_URI`; local throwaway Postgres only) |
| | `tests/watomation/routers/test_telegram_webhook.py` | 404 / 403 / invalid update / handler failure still 200 / retried update handled once |
| **Rider bot** (R1) | `channels/telegram/rider/router.py`, `rider/commands.py` | `@ByteloopRidersBot` (bot key `rider`, webhook `/telegram/rider/webhook`): `/start` onboarding by shared phone (contact.user_id must equal from_user.id), town / vehicle buttons, `/help`, `/whoami`, text fallback; ops alerts through `WALogger`. Registered only when configured (`config.rider_bot`, D54). Plan: `plans/telegram-rider-bot-plan.md` |
| | `channels/telegram/rider_links.py` | `link`, `set_profile`, `choices`, `profile`: thin wrappers over the `t_rider_*` RPCs |
| | `channels/telegram/callbacks.py`, `keyboards.py` | `RiderSignup` (`rsu:t\|v:<value>`), `RiderOffer` (`ro1:<dispatch_id>:a\|d`, R4); `rider_choice_kb`, `rider_offer_kb`, `location_request_kb` |
| Rider messaging | `ordelo/rider_messaging/` | `RiderMessenger` interface (`say`, `send_place`, `request_location`, `send_contact`, `mark`, `offer_job`, `offer_closed`), WhatsApp adapter (byte-identical pywa calls), Telegram adapter (HTML, reactions, edit-in-place), `for_rider()`, `use_messenger()`, recording fake. Wired into the agent in R3 |
| Pauses | `ordelo/pauses.py` | `pause`, `resume`, `current` over `pause_start` / `pause_end` / `pause_current` (ADR 0013); used by `/off` `/on` from R5 |
| | `ordelo_datamodels/telegram/t_rider_onboarding.sql`, `availability/pauses.sql`, `availability/job_pause_sweep.sql`, `core/rider_master.sql`, `migrations/rider_telegram_r1.sql`, `test_support/test_rider_onboarding.sql` | rider onboarding RPCs, pauses, the sweep (R5), the R1 target shape of `rider_master`, the one-off migration with pre-checks, the live harness |
| | `tests/channels/telegram/test_rider_router.py`, `test_rider_links.py`, `tests/ordelo/test_rider_messaging.py`, `test_pauses.py`, `tests/sql/test_rider_*`, `test_pauses_sql.py` | `FakeRiderDb` (conftest) mimics the RPCs; SQL tests on the isolated database incl. the migration on a pre-R1 table |
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
2. The function is defined **in the same feature file as the table it works on** (`telegram/t_invites.sql` holds `t_invites`, the view, and all three RPCs, plus grants and operator SQL). Feature files live in capability folders of `ordelo_datamodels/`, never in `migrations/` (see `ordelo_datamodels/README.md`).
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
| Header of the SQL feature file (`telegram/t_invites.sql`) | the Python module and functions that call each RPC, and the other tables it touches |
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
| table `t_invites` | `telegram/t_invites.sql` | none directly (only through the RPCs) | n/a | `FakeInviteDb` mimics it |
| view `t_invites_shareable` | `telegram/t_invites.sql` | none (operator SQL and agents only) | n/a | n/a |
| function `t_new_invite_code()` | `telegram/t_invites.sql` | none (column default) | n/a | n/a |
| trigger function `t_invites_normalize_phone()` | `telegram/t_invites.sql` | none (trigger) | n/a | n/a |
| RPC `t_invite_preview(p_code, p_bot_key, p_user_id)` | `telegram/t_invites.sql` | `invites.preview_invite` | `/start <code>` | `test_invites.py`, `test_rest_admin_router.py` |
| RPC `t_claim_invite(...)` | `telegram/t_invites.sql` | `invites.claim_invite` | Yes button | `test_invites.py`, `test_rest_admin_router.py` |
| RPC `t_linked_restaurants(p_bot_key, p_user_id)` | `telegram/t_invites.sql` | `invites.linked_restaurants` | `/start`, `/whoami` | `test_invites.py`, `test_rest_admin_router.py` |
| config row `ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME` | operator SQL (runbook) | none (read by the view) | n/a | n/a |
| table `t_inbox` | `telegram/t_inbox.sql` | none directly (through the RPCs) | n/a | `FakeInboxDb` mimics it; `tests/sql/test_t_inbox_sql.py` |
| RPC `t_inbox_claim(p_bot_key, p_update_id, p_kind, p_tuid)` | `telegram/t_inbox.sql` | `inbox.claim` (via `InboxMiddleware`) | every update | `test_inbox.py`, `test_telegram_webhook.py`, `tests/sql/test_t_inbox_sql.py` |
| RPC `t_inbox_finish(p_bot_key, p_update_id, p_status, p_error)` | `telegram/t_inbox.sql` | `inbox.finish` (via `InboxMiddleware`) | every update | `test_inbox.py`, `tests/sql/test_t_inbox_sql.py` |
| constraint `delivery_summary_status_check` | `restaurant_order_decision.sql` (and `delivery/delivery_summary.sql`) | none | n/a | `tests/sql/test_restaurant_decision_sql.py` |
| function `restaurant_admin_label(p_phone)` | `restaurant_order_decision.sql` | none directly (called inside the two functions below) | "by X" in replies | `tests/sql/test_restaurant_decision_sql.py` |
| RPC `restaurant_order_decide(p_order_number, p_order_type, p_decision, p_admin_phone, p_channel)` | `restaurant_order_decision.sql` | `restaurant_decision.decide` | WhatsApp Accept tap (`_update_restaurant_order_status`) | `test_restaurant_decision.py`, `test_on_callback_wa_handler.py`, `tests/sql/test_restaurant_decision_sql.py` |
| RPC `restaurant_order_set_pickup(p_order_number, p_order_type, p_pickup_time, p_admin_phone, p_channel)` | `restaurant_order_decision.sql` | `restaurant_decision.set_pickup` | WhatsApp pickup-time tap (`handle_pickup_time_selection`) | `test_restaurant_decision.py`, `test_on_callback_wa_handler.py`, `tests/sql/test_restaurant_decision_sql.py` |
| table `t_order_alerts` | `telegram/t_order_alerts.sql` | none (written and read by the sweep only) | n/a | `tests/sql/test_order_cards_sql.py` |
| table `t_sent_messages` | `telegram/t_sent_messages.sql` | none directly (through the RPCs) | n/a | `FakeCardStore` mimics it; `tests/sql/test_order_cards_sql.py` |
| function `t_order_admin_phone(p_bot_key, p_tuid, p_rest_ref)` | `restaurant_order_decision.sql` | none (used by the two RPCs below) | n/a | `tests/sql/test_order_taps_sql.py` (D14: claimed invite for the restaurant + phone in `admins`) |
| RPC `t_order_decide(p_bot_key, p_tuid, p_order_number, p_order_type, p_decision)` | `restaurant_order_decision.sql` | `CardStore.decide` | Accept / Decline buttons (`OrderCards.tap`) | `test_order_taps.py`, `test_order_card_store.py`, `tests/sql/test_order_taps_sql.py` (incl. 6 concurrent taps: one winner) |
| RPC `t_order_set_pickup(p_bot_key, p_tuid, p_order_number, p_order_type, p_minutes)` | `restaurant_order_decision.sql` | `CardStore.set_pickup` | pickup-time buttons (`OrderCards.tap`) | `test_order_taps.py`, `test_order_card_store.py`, `tests/sql/test_order_taps_sql.py` (pickup = order time + minutes) |
| function `t_order_card_status(p_rcs, p_pickup)` | `telegram/t_order_alerts.sql` | none (used by the functions below) | n/a | `tests/sql/test_order_cards_sql.py`; keys match `model.Status` |
| function `t_order_card_row(p_order_number, p_order_type)` | `telegram/t_order_alerts.sql` | none (used by the functions below) | n/a | `tests/sql/test_order_cards_sql.py` |
| function `t_order_card_destinations(p_bot_key, p_rest_ref)` | `telegram/t_order_alerts.sql` | none directly (inside the snapshot) | n/a | `tests/sql/test_order_cards_sql.py` (the one place that says where cards go) |
| RPC `t_order_card_snapshot(p_bot_key, p_order_number, p_order_type)` | `telegram/t_order_alerts.sql` | `CardStore.snapshot` | `OrderCards.remind`, `refresh` | `test_order_cards.py`, `tests/sql/test_order_cards_sql.py` |
| RPC `t_order_card_sent(...)` | `telegram/t_sent_messages.sql` | `CardStore.card_sent` | `OrderCards.remind` | `test_order_cards.py`, `tests/sql/test_order_cards_sql.py` |
| function `t_order_cards_stale(p_bot_key, p_order_number, p_order_type)` | `telegram/t_order_alerts.sql` | none (used by take and the sweep) | n/a | `tests/sql/test_order_cards_sql.py` |
| RPC `t_order_cards_take(p_bot_key, p_order_number, p_order_type)` | `telegram/t_order_alerts.sql` | `CardStore.take_for_refresh` | `OrderCards.refresh` | `test_order_cards.py`, `tests/sql/test_order_cards_sql.py` (6 concurrent workers, each copy claimed once) |
| RPC `t_order_card_mark(p_id, p_outcome, p_card_status, p_close)` | `telegram/t_sent_messages.sql` | `CardStore.mark` | `OrderCards.remind`, `refresh` | `test_order_cards.py`, `tests/sql/test_order_cards_sql.py` |
| columns `delivery_summary.ready_at/ready_by/ready_dispatch_id/pickup_time_initial/pickup_adjusted_by/pickup_adjusted_at`, `takeaway_summary.ready_at/ready_by`, `t_sent_messages.dispatch_id` | `restaurant_ready_adjust_notices.sql` | none directly (through the RPCs) | n/a | `tests/sql/test_restaurant_ready_adjust_notices_sql.py` |
| RPC `restaurant_order_ready(p_order_number, p_order_type, p_admin_phone, p_channel)` | `restaurant_ready_adjust_notices.sql` | `restaurant_actions.ready` | WhatsApp Ready buttons (`admin_collection_ready`, `admin_takeaway_ready`) | `test_restaurant_actions.py`, `test_on_callback_wa_handler.py`, SQL test (first Ready per dispatch wins) |
| RPC `restaurant_order_adjust_pickup(p_order_number, p_target, p_admin_phone, p_channel)` | `restaurant_ready_adjust_notices.sql` | `restaurant_actions.adjust_pickup` | WhatsApp +10 / +20 (`admin_adjust_pickup_time`) | same |
| RPC `t_order_ready(p_bot_key, p_tuid, p_order_number, p_order_type)` | `restaurant_ready_adjust_notices.sql` | `restaurant_actions.ready` | Telegram Ready (`Receipts.tap`) | `test_receipts.py`, SQL test (D14 authorisation) |
| RPC `t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)` | `restaurant_ready_adjust_notices.sql` | `restaurant_actions.adjust_pickup` | Telegram +10 / +20 (`Receipts.tap`) | `test_receipts.py`, SQL test (relative to the original pickup) |
| function `t_receipt_status(p_order_number, p_order_type, p_dispatch_id)` | `restaurant_ready_adjust_notices.sql` | none (used by the functions below) | n/a | SQL test; keys match `receipts/model.py` |
| RPC `t_receipt_snapshot(p_bot_key, p_order_number, p_order_type, p_dispatch_id)` | `restaurant_ready_adjust_notices.sql` | `ReceiptStore.snapshot` | `Receipts.send`, `refresh` | `test_receipts.py`, SQL test |
| RPC `t_receipt_sent(...)` | `restaurant_ready_adjust_notices.sql` | `ReceiptStore.receipt_sent` | `Receipts.send` | `test_receipts.py`, SQL test (a newer receipt deletes only older ones) |
| functions `t_receipts_stale`, RPC `t_receipts_take(p_bot_key, p_order_number, p_order_type)` | `restaurant_ready_adjust_notices.sql` | `ReceiptStore.take_for_refresh` | `Receipts.refresh` | `test_receipts.py`, SQL test (claims, 30 s re-offer, receipts older than 3 days left alone) |
| RPC `t_notice_targets(p_bot_key, p_rest_ref, p_order_number, p_reply_kind)` | `restaurant_ready_adjust_notices.sql` | `NoticeStore.targets` | `Notices.send` | `test_notices.py`, SQL test |
| RPC `t_notice_sent(...)` | `restaurant_ready_adjust_notices.sql` | `NoticeStore.notice_sent` | `Notices.send` | `test_notices.py`, SQL test |
| function `job_t_receipt_refresh()` | `restaurant_ready_adjust_notices.sql` | none (pg_cron every 5 s, operator step) | POSTs `{"receipts": [...]}` to `/telegram/rest-admin/order-alerts` | SQL test (marks only on 2xx) |
| function `job_t_order_alerts()` | `telegram/t_order_alerts.sql` | none (pg_cron every 5 s, operator step) | POSTs `/telegram/rest-admin/order-alerts` | `tests/sql/test_order_cards_sql.py` (seed, cancel, collapse, mark only on 2xx, stale refreshes) |
| function `t_housekeeping()` | `telegram/t_housekeeping.sql` | none (pg_cron daily, operator step) | n/a | `tests/sql/test_order_cards_sql.py` |
| config rows `TGRAM_ORDER_ALERT_OFFSETS_SECS`, `TGRAM_INBOX_RETENTION_DAYS`, `TGRAM_LEDGER_RETENTION_DAYS` | `telegram/t_order_alerts.sql` (offsets); retention keys are read by `telegram/t_housekeeping.sql` | none (read by the SQL) | n/a | `tests/sql/test_order_cards_sql.py` |
| existing function `parse_alert_offsets(p_config_key)` | `dispatch/job_rider_pickup_alerts.sql` | none | n/a | copied into `tests/sql/minimal_schema.sql` |
| existing table `restaurant_master` | existing migrations | none (joined inside the RPCs for the restaurant name) | n/a | n/a |
| columns `rider_master.channel/tuid/tcid/t_username/t_first_name/t_linked_at/phone_verified`, unique `rider_id`, `rider_master_tuid_uidx` | `core/rider_master.sql` (+ `migrations/rider_telegram_r1.sql`) | none directly (through the RPCs); `ordelo/rider_messaging/factory.for_rider` reads `channel`, `tcid` | n/a | `tests/sql/test_rider_onboarding_sql.py`, `test_rider_telegram_r1_migration_sql.py` |
| RPC `t_rider_link(p_tuid, p_tcid, p_phone, p_username, p_first_name)` | `telegram/t_rider_onboarding.sql` | `rider_links.link` | contact message (rider bot) | `test_rider_links.py`, `test_rider_router.py`, SQL test (every result, concurrent first link) |
| RPC `t_rider_set_profile(p_tuid, p_town, p_vehicle_type)` | `telegram/t_rider_onboarding.sql` | `rider_links.set_profile` | town / vehicle buttons | same |
| RPC `t_rider_choices()` | `telegram/t_rider_onboarding.sql` | `rider_links.choices` | sign-up buttons | same |
| RPC `t_rider_profile(p_tuid)` | `telegram/t_rider_onboarding.sql` | `rider_links.profile` | `/start`, `/whoami`, fallback | same |
| function `t_rider_phone_digits(p_phone)` | `telegram/t_rider_onboarding.sql` | none (inside `t_rider_link`) | n/a | SQL test |
| table `pauses`, functions `is_paused`, `pause_duration` | `availability/pauses.sql` | none directly; `get_available_riders()` calls `is_paused` | n/a | `tests/sql/test_pauses_sql.py`, `test_rider_onboarding_sql.py` (dispatch gate) |
| RPCs `pause_start`, `pause_end`, `pause_current` | `availability/pauses.sql` | `ordelo/pauses.pause` / `resume` / `current` | `/off`, `/on`, `/shift` (R5) | `tests/ordelo/test_pauses.py`, `tests/sql/test_pauses_sql.py` |
| function `job_pause_sweep()` | `availability/job_pause_sweep.sql` | none (pg_cron every minute, from R5) | POSTs `/pause-hooks/sweep` (R5) | `tests/sql/test_pauses_sql.py` (clock decides, marks only on 2xx) |
| function `get_available_riders(...)` (changed) | `dispatch/job_create_dispatch.sql` | none | n/a | `tests/sql/test_rider_onboarding_sql.py` (`status = 'active'`, not paused) |

## 7. Invite lifecycle and operations

`pending → claimed` (person confirms before `expires_at`), `pending → expired` (computed when `expires_at` passes), `pending|claimed → revoked` (operator). There is no way back to `pending`; issue a new invite. A claim records `telegram_user_id`, `telegram_chat_id`, username and first name. `phone_verified` is reserved for a later flow and is never set today.

Operators (and agents) create invites, read the link from `t_invites_shareable`, see who claimed what, and revoke, using the SQL in the footer of `telegram/t_invites.sql` and the **Telegram Invites** section of the [database-operations skill](../.claude/skills/database-operations/SKILL.md). Deleting rows needs explicit approval; revoke instead.

Setup for a new bot or environment: add the AWS keys, set the `ordelo_config` username row, restart, run notebook cell 4 to set the webhook, then send `/start` with an invite link. Details in the [local testing runbook](local-testing-runbook.md).

## 8. Testing

### Interactive scratchpad

Send `/scratchpad` to the main restaurant-admin bot to open its demo menu. Try formatted text,
reply/edit/delete, streamed drafts, a button-driven delivery tracker and restaurant order card,
inline keyboards, **buttons inside the text**, location/contact request keyboards, maps, venues,
demo contacts, dice, CSV files, message effects, simulated errors and bot info. Each progress tap
edits its own demo message. All order/contact/address data is fictional; the router does not call
business RPCs or perform real order/payment transitions. The ordinary inbox middleware still
records Telegram updates. Contact/location replies are acknowledged only while a scratchpad
request is pending; `/scratchpad` clears that state and removes the reply keyboard.

The entire feature lives in `channels/telegram/rest_admin/scratchpad.py`. To unmount it, remove
`dp.include_router(build_scratchpad_router())` and its import from `channels/telegram/bots.py`,
then restart the app. It is a sibling **before** the main restaurant router: the latter's text
fallback would otherwise swallow `/scratchpad`. No separate bot token, polling process or
webhook change is needed. The command can be typed directly; it does not change the published
`/start`, `/help`, `/whoami` command list. After loading the code, use the existing webhook;
this change does not deploy or restart a remote service.

Offline coverage: `tests/channels/telegram/test_scratchpad.py` exercises the real dispatcher,
the menu, all 27 demo entries, in-place edits, callback answers, private-chat/actor checks,
scoped contact/location input, unsupported-feature errors and removal of the router.
These checks do not establish live Telegram rendering or callback delivery.

Choose **Salisbury Mini App** → **Open Salisbury** to launch
`https://restaurant.ordelo.app/town/salisbury` inside Telegram via an inline button's
`web_app=WebAppInfo(...)`. This opens the real storefront, not dummy menu data. The launcher
uses the same private-chat restriction as the other examples; no BotFather menu or webhook
registration is changed. Offline checks verify the Web App button and exact URL, not a live launch.

Six choices demonstrate newer rich-message features supported by aiogram 3.31.0:

- **Expandable receipt:** a heading, total, native collapsed details sections, an item table and kitchen/handover notes. Opening the details uses Telegram's native disclosure control.
- **Coloured actions:** green Accept, red Decline and blue Reset. A decision disables both decision actions using `DisabledButton()` with no callback data.
- **Show progress:** an embedded rich button expands/collapses four stages. Initially Order Accepted and Rider Assigned are green and disabled, Food pickup is next, and Delivery complete is disabled. Simulating pickup unlocks delivery; old callbacks cannot roll the demo back or skip pickup. Telegram supports `success` (green), `danger` (red), `primary` (blue) and `link`, **not an orange background**. The next step uses a 🟠 marker with the supported blue style. Disabled appearance is rendered by the Telegram client.
- **Pickup: prep presets:** embedded 10/20/30 minute choices with a selected indicator and an absolute pickup time; Confirm freezes the choices, Edit time reopens them.
- **Pickup: adjust time:** the sentence contains the pickup time and −5/+5/+10 minute controls, followed by Confirm/Edit. The timestamp stays fixed across redraws and is formatted for the reader by `RichTextDateTime`.
- **Pickup: ready / hold:** an embedded kitchen-status button, Mark food ready, and +10/+20 minute holds. Marking ready turns the status green and disables the completed action and hold controls; Restart resets the demo.

These six examples store temporary state per demo message in the existing dispatcher's
memory-backed FSM storage. A new `/scratchpad`, clearing scratchpad input state, or a restart
expires those instances; tap a menu choice to open a fresh one. No state is persisted to order
tables. This temporary state is an interaction demo, not a replacement for production order RPCs.
API references: [rich buttons](https://docs.aiogram.dev/en/v3.31.0/api/types/rich_message_button.html),
[details](https://docs.aiogram.dev/en/v3.31.0/api/types/input_rich_block_details.html),
[disabled buttons](https://docs.aiogram.dev/en/v3.31.0/api/types/disabled_button.html).


- `tests/conftest.py` stubs the AWS secret (including the `tgram_rest_admin_*` keys), so `import config` works in tests.
- Handlers are tested through a real aiogram `Dispatcher` with a `RecordingSession` (no network); the database is replaced by `FakeInviteDb`, which mimics the three RPCs' return shapes. If an RPC's contract changes, change the fake in the same commit.
- The webhook tests cover 404 (unknown bot), 403 (bad or missing secret), invalid updates, handler failure still returning 200, and a retried update being handled once (the `t_inbox` outcome is asserted, not just the 200).
- **SQL against an isolated database:** `tests/sql/` applies the real migration files to a throwaway local Postgres and tests the functions, grants and races (8 concurrent claims -> exactly one winner). Set `ORDELO_TEST_DB_URI` to a local server (`tests/sql/conftest.py` refuses non-local hosts and resets the `public` schema); without it the tests are skipped. Never point it at the shared Supabase database.
- Nothing here proves the SQL itself: it has been parsed, and exercised live for `t_invite_preview` and the insert path, but the full claim path needs a real tap in Telegram.

## 9. Not done yet

- **Alias order prefixes:** order cards are looked up by the order number's prefix; a restaurant whose orders use an alias prefix (`_REST_REF_ALIAS_MAP`) gets no cards until `t_order_card_destinations()` resolves the alias.
- **Scheduling:** `telegram/t_order_alerts.sql` and `restaurant_admin/restaurant_ready_adjust_notices.sql` carry their live `cron.schedule` statements; `t_housekeeping()` (`telegram/t_housekeeping.sql`) is **not scheduled on live** (docs/to-do.md). Before the jobs were scheduled nothing was sent and nothing was purged.
- **Long cards:** an order with a very long item list is not truncated to Telegram's 4096 characters.
- **Order actions** are authorised per tap (claimed invite for the restaurant AND the invite phone in `restaurant_master.admins`). Ready and +10 / +20 are built (Phases 7-8, on the kitchen receipt). Not built: adjusting a takeaway pickup time, a takeaway `completed` writer (its receipt stays "ready"), and a tap on a card that has no ledger row (an old card sent before the migration is answered but not redrawn).
- **Phases 7-8 are scheduling and live checks for the owner:** apply `restaurant_ready_adjust_notices.sql`, schedule `job_t_receipt_refresh()`, put the dummy rider in `overwatch_list`, deploy, then run the live script (`test_support/test_restaurant_notices.sql`). Out of scope: rider-nearby (G) and availability enquiry (J).
- **Rider bot:** R1 (onboarding by verified phone) is scaffolded; offers, the job conversation, locations, `/off` / `/on` and the pause sweep are phases R2-R6 of `plans/telegram-rider-bot-plan.md`. Restaurant admins still link by invite (no phone-verified flow).

## Change log

Add one line per change, newest first: date, what changed, files.

- 2026-10-22: Both Telegram notebooks now select `rest_admin` or `rider` with `BOT_KEY` in their first cell. Setup uses the selected settings, dispatcher, webhook URL and command list; scratchpad uses the selected bot and skips its restaurant-admin-only rich text button demo for riders. `notebooks/telegram/tgram_setup_bot.py`, `notebooks/telegram/tgram_scratchpad.py`.
- 2026-10-22: Rider bot R0 + R1 scaffold (plan `plans/telegram-rider-bot-plan.md`, D39-D54; ADR 0011 Amendment 3, ADR 0012 Amendment 1, ADR 0013): `config.tgram_setting.optional_bot` / `rider_bot`, `bots.build_rider_dispatcher`, `channels/telegram/rider/`, `rider_links.py`, `RiderSignup` / `RiderOffer`, `ordelo/rider_messaging/`, `ordelo/pauses.py`; SQL `core/rider_master.sql` (target shape), `telegram/t_rider_onboarding.sql`, `availability/pauses.sql`, `availability/job_pause_sweep.sql`, `get_available_riders` gate, `migrations/rider_telegram_r1.sql`, harness `test_support/test_rider_onboarding.sql`; `tests/sql/conftest.py` fixed (missing files, pg_cron stub). Apply the migration (pre-checks first), add the `tgram_rider_*` secrets, deploy, register the rider webhook.
- 2026-10-16: Added Salisbury Mini App to `/scratchpad`: private-chat `WebAppInfo` button opens the real `https://restaurant.ordelo.app/town/salisbury` storefront inside Telegram. Router, dispatcher test and both guides updated; no webhook/menu registration changed.
- 2026-10-16: Six restaurant-focused rich-message scratchpad examples: native receipt details/table, coloured decisions, expandable Show progress with genuinely disabled completed/future steps, and embedded prep-preset, pickup-time and ready/hold controls. Temporary per-message demo state guards completed actions and preserves selected timestamps; dispatcher tests cover the payloads and transitions. `scratchpad.py`, `test_scratchpad.py`, recording-session support in `conftest.py`, and both guides updated. Orange represented by 🟠 because the Bot API has no orange button style.
- 2026-10-16: Main-bot `/scratchpad` playground in `rest_admin/scratchpad.py`, mounted before the main router in `bots.py`; 20 private-chat demos, working rich-text button callbacks and demo order/tracker controls, scoped reply-keyboard input and offline dispatcher tests. Notebook cell 7a reuses the renderer; separate-token/polling cells removed. Unmount with one router include; existing webhook and business actions retained.
- 2026-10-16: `notebooks/telegram/tgram_scratchpad.py` cells 7a–7b demonstrate `RichTextButton` inside a rich-message paragraph, callback acknowledgement and in-place status/button edits with aiogram 3.31.0; optional polling uses a separate demo bot and refuses an existing webhook. Verified offline; no live send or webhook change.
- 2026-10-16: Files renamed to `telegram/t_inbox.sql`, `t_invites.sql`, `t_order_alerts.sql`; `t_sent_messages` (+ its RPCs) and `t_housekeeping()` split into `telegram/t_sent_messages.sql` and `telegram/t_housekeeping.sql`; every file reconciled with live and documented to the standard in `ordelo_datamodels/README.md` (plan: `plans/ordelo-database-organisation-plan.md`).
- 2026-10-16: SQL moved out of `migrations/` into feature folders: `ordelo_datamodels/telegram/` (`create_t_inbox.sql`, `create_t_invites.sql`, `create_t_order_alerts.sql`) and `ordelo_datamodels/restaurant_admin/` (`restaurant_order_decision.sql`, `restaurant_ready_adjust_notices.sql`); `init_delivery` / `init_takeaway` no longer `RETURNING *`.
- 2026-10-15: Phase 8a, plain restaurant notices on both channels: `restaurant_notifier` gains `AutoAccepted`, `RiderAlert`, `DeliveryCompleted`, `Feedback`; new `rest_admin/notices.py`; call sites in `delivery_hooks` (auto-accept notice now sent AFTER the update, for both channels), `takeaway_hooks`, `rider_agent` and `customer_hooks` switched to `restaurant_notifier.notify`; `wa_senders` gains `admin_auto_accept_notice`, `admin_delivery_completed`, `rider_alert_text` and loses the dead `admin_delivery_driver_nearby` / `admin_delivery_complete_notification` and `REST_MASTER`; tests now default the Telegram side to a no-op (`quiet_telegram_notices`).
- 2026-10-15: Phase 7, kitchen receipts and actions: `restaurant_ready_adjust_notices.sql` (shared Ready / adjust RPCs, receipt and notice functions, `job_t_receipt_refresh`), `restaurant_actions.py`, `rest_admin/receipts/`, `restaurant_notifier` (`KitchenReceipt`, `TakeawayReceipt`), WhatsApp Ready / +10 / +20 handlers switched to `restaurant_actions` (texts unchanged), `FakeActionsDb`, `FakeReceiptStore`, SQL and live-script tests. Apply the migration, schedule `job_t_receipt_refresh()`, then deploy.
- 2026-10-15: Phase 5, Telegram taps: `OrderCards.tap`, `rest_admin/orders.py` (`build_orders_router`, one `OrderAction` handler), `CardStore.decide` / `set_pickup`, SQL `t_order_admin_phone` / `t_order_decide` / `t_order_set_pickup` appended to `restaurant_order_decision.sql` (re-run it), `FakeCardStore` decide/set_pickup, dispatcher-level tap tests, SQL tap tests. Authorised by the Telegram user id only (group-ready).
- 2026-10-15: Phase 4, order cards (remind / refresh) + ledger: `create_t_order_alerts.sql` (`t_order_alerts`, `t_sent_messages`, card functions, `job_t_order_alerts`, `t_housekeeping`), `channels/telegram/rest_admin/order_cards/` (`model`, `store`, `io`, `OrderCards`), `OrderAction`, `TelegramBot.cards`, `POST /telegram/rest-admin/order-alerts`, `FakeCardStore`, model / cards / route / SQL tests. Run the migration, deploy, then schedule the two cron jobs.
- 2026-10-15: Phase 3, shared decision functions + R1-a: `restaurant_order_decision.sql` (`'declined'` allowed on `delivery_summary.status`, `restaurant_admin_label`, `restaurant_order_decide`, `restaurant_order_set_pickup`), `utils_common/order_management/restaurant_decision.py`, WhatsApp accept/decline/pickup handlers switched to it (a losing tap is told who decided), delivery decline handler now terminal + payment cancel + customer notice (mirrors takeaway), `FakeDecisionDb`, SQL tests. Run the migration before deploying.
- 2026-10-15: Phase 2, durable inbox: `t_inbox` + `t_inbox_claim` / `t_inbox_finish` (`create_t_inbox.sql`), `channels/telegram/inbox.py` (`InboxMiddleware`, at-most-once, fail open), registered in `bots.py`; `FakeInboxDb`, `tests/channels/telegram/test_inbox.py`, `tests/sql/` isolated-database tests. Run the migration before deploying.
- 2026-10-15: Telegram layer scaffold: settings (fail-fast), registry, webhook route, restaurant-admin bot, invite flow (`t_invites`, three RPCs, `invites.py`), service-role client, delivery-lag logging, notebooks, tests, docs. Renamed `tgram_*` database objects to `t_*` (run `drop_tgram_invites.sql`, then `create_t_invites.sql`).
