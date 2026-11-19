# OrdeloAgent to-do

Open items that are known but deliberately not fixed yet. Each entry says where it was found, why it matters and
what "done" looks like. Remove an entry when it is done and say so in the commit message.

## Database findings (live check, 16 Oct 2026)

Found while organising `ordelo_datamodels/` (plan: [`plans/ordelo-database-organisation-plan.md`](../plans/ordelo-database-organisation-plan.md),
evidence: [`plans/ordelo-database-gate1-review.md`](../plans/ordelo-database-gate1-review.md) section B). The owner chose to
record these as follow-ups; the organisation work documents them but does not change live behaviour.

- [ ] **URGENT: lock down `fly_config` and rotate the Fly tokens.** `fly_config` holds the Fly API tokens that can stop and
  start production machines (2 rows with tokens on 16 Oct 2026). Live has RLS **off** and default grants, so the
  public anon key can read them through PostgREST. Since 16 Nov 2026 the lock-down (`ALTER TABLE public.fly_config ENABLE
  ROW LEVEL SECURITY;` and `REVOKE ALL ON TABLE public.fly_config FROM anon, authenticated;`) is active in
  `platform/fly_config.sql`, together with `fly_idle_suspend()`, but the file has not been applied to live yet. Done when
  the file is applied, both tokens are rotated, and the LIVE CHECK line in the file is updated. Apply this before
  scheduling `job_fly_idle_suspend` (docs/fly.io-deploy-guide.md §10g).

- [ ] **Schedule `job_payment_init_reconciler`.** `migrations/ordelo_agg_r1.sql` says to run it every 2 minutes, but
  `cron.job` has no such job, so payment-init reconciliation is not running. Done when the job is scheduled (or the
  owner records that it is intentionally off) and the job's SQL file shows the live schedule.
- [ ] **Schedule `t_housekeeping`.** Telegram inbox and sent-message retention (`tgram_inbox_retention_days`,
  `tgram_ledger_retention_days`) never runs. Done when the job runs nightly and `telegram/t_housekeeping.sql` shows it.
- [ ] **Create the `t_invites` phone-normalise trigger.** The function `t_invites_normalize_phone()` is live but the
  trigger that calls it is not, so `t_invites.phone_number` is stored as typed. Done when the trigger exists live.
- [ ] **`job_restaurant_confirmation_timeout` is superseded by `process_restaurant_confirmation()` + `restaurant_confirmation_policy()`** (confirmation timeout action, ADR 0014). If the orphan is still on live after the rollout, drop it rather than reviving it.
- [ ] **Decide on `job_restaurant_confirmation_timeout`.** It is documented (`docs/delivery_process.md`, `.specify/design/`)
  but not scheduled; the 10-second `process_restaurant_confirmation` job appears to have replaced it. Done when it is
  either scheduled or moved to `_orphans/` and the docs say which job handles timeouts.
- [ ] **Align the rider pickup-alert cadence.** `dispatch/job_rider_pickup_alerts.sql` says the sweep must run at least
  as often as the smallest gap between two offsets (the defaults include 5 and 7 minutes, so every 2 minutes); the live
  cron job runs every 5 minutes, so those checkpoints can collapse into one alert. Change the schedule or the offsets.
- [ ] **Fix or drop `match_documents()`.** It declares `id uuid` but `documents.id` is text, so calling it raises
  (byteloop_agent/documents.sql).
- [ ] **Apply or drop the unapplied indexes.** `idx_thread_active_rest_ref_last_access`
  (`migrations/add_stale_thread_dispatch_index.sql`) and the two `rider_location` indexes were never created live.
- [ ] **Lock down `fly_post()`.** It is `SECURITY DEFINER`, reads the Fly API token from `fly_config`, and is still
  executable by PUBLIC/anon/authenticated on live: the `REVOKE` in `platform/fly_post.sql` was never applied (it is
  kept commented there so the file matches live). `job_process_owntracks()` is also `SECURITY DEFINER` with default
  grants. Done when both are revoked from PUBLIC/anon/authenticated live and the files carry the active `REVOKE`.
- [ ] **Security review of row-level security.** RLS is off on most tables (`rider_master`, `restaurant_master`,
  `customer_master`, `delivery_*`, `takeaway_summary` …) while restaurant-frontend reads several of them with the
  publishable (anon) key. Only `t_*`, `web_*`, `wa_location_*` and `order_access_grant` have RLS.
- [ ] **Remove dead Python.** `ordelo/agent_app_handlers.py::process_dispatch_response_from_rider_sync` (only caller of the
  live `dispatch_accept_func`) is never called; several modules still query the legacy `foodorder` / `orderitem` tables,
  which have never received a row.
- [ ] **Decide on the orphan candidates** listed in `ordelo_datamodels/_orphans/` (live objects with no caller anywhere):
  keep, or drop with explicit approval.
- [ ] **Rotate the Supabase database password.** A fragment appeared in local tool output during the live check (not
  sent anywhere).

## Rider bot findings (design session, 22 Oct 2026)

Found while planning the Telegram rider bot ([ADR 0011, Amendment 3](adr/0011-telegram-operations-messaging-stays-in-ordeloagent.md#amendment-3---22-october-2026-rider-bot-phases-r0-r6)).
Not fixed by that plan unless a phase says so.

- [ ] **`job_close_thread` header does not match live.** `agent_threads/job_close_thread.sql` says it is "called from Python,
  not by pg_cron"; the owner says the stale-thread close is a scheduled cron job. Read `cron.job` and make the file show
  the live schedule (`drift_check.py`).
- [ ] **`job_close_thread` can say goodbye to customers.** It selects idle threads of EVERY agent except `WEB` and its payload
  has no `agent`, so `delivery_hooks.close_threads` cannot skip anything: idle restaurant-agent customer threads
  (`ELAS-…`) get "Ending the conversation…" from Ordelo's WhatsApp number (their threads are not closed, because
  `make_threads_inactive` is scoped to the ORDELO agent). Phase R2 makes the rider path close only `ORDELO-dispatch-*`
  rows; done when the job itself filters by agent (or the owner records that it is intended).
- [x] **`fapp_ordelo_agent.py /threads` and `/debug-state-by-thread` query `from_number`,** a column the `thread` table no
  longer has (renamed to `recipient`). Fixed in R2 (both use `recipient`; debug reads never create or touch a thread).
- [ ] **Race-hardening of rider assignment** (ADR 0011 point 4): `dispatch_response` reads state and writes separately.
  Deferred by D48; Telegram does not make it worse.
- [ ] **Rename `wa_location*`** to channel-neutral names now that Telegram locations are built (R5: `receive_current_location`, with `receive_whatsapp_location` kept as an alias). Cosmetic; touches many files.
- [ ] **Retire the location wire-source mapping.** Telegram locations are stored as `telegram_current` but sent to restaurant-agents as `whatsapp_current` (`wire_source()` in `ordelo_datamodels/wa_location_pymodels.py`), because its callback validates exactly two values. Done when restaurant-agents accepts `telegram_current` and the mapping is removed.
- [ ] **Admin roster P2 and P3.** P1 is built (roster, contact-share link, `/channels`, sys-admin UI) but unapplied. P2 flips `WHATSAPP_FOLLOWS_CHANNELS` and makes `whatsapp_phones()` honour channels (linking stops WhatsApp). P3 deletes the TRANSITION invite fallbacks and retires `t_invites`. Plan: `plans/restaurant-admin-roster-onboarding-plan.md`.
- [ ] **Single-admin restaurants can never pause alerts** (D52 last-admin guard). STRK has one admin, so the owner's own `/off` on the restaurant bot is refused until a second admin phone is added to `restaurant_master.admins` (owner decision).
- [ ] **Bring the pause sweep onto its planned schedule.** Live `job_pause_sweep` is active at `*/5 * * * *` (confirmed 23 Oct); `availability/job_pause_sweep.sql` targets `* * * * *`. Apply the whole job file when the owner wants one-minute messages, then verify `cron.job.schedule`, `command` and `active`. The five-minute schedule only delays reminder and back-on messages; `is_paused()` still changes availability on time.
- [ ] **Pause taps and the inbox review.** `rp1:` / `ap1:` taps use `process_once` (so a redelivered tap cannot restart a break after `/on`); include them in the inbox review below.
- [ ] **Delete `agent_app_handlers.initial_handle_of_rider_response`.** Superseded by `ordelo/dispatch_actions.respond_to_offer`
  (R4, shared by WhatsApp and Telegram); it has no production caller left. Delete with its tests after R4 has run live.
- [ ] **Two agent turns on one rider thread can overlap.** A Telegram text (run in the background), a job-card tap and a
  hook can reach the same thread at the same moment; LangGraph then interleaves state updates. WhatsApp has the same gap
  today. A per-thread lock (in-process `asyncio.Lock` keyed by thread id, or `pg_advisory_lock`) would serialise them.
- [ ] **`rider_master` holds Telegram ids with RLS off.** Part of the existing row-level-security review; `tuid`/`tcid` are
  now readable with the anon key.

## Rider alert findings (23 Oct 2026)

- [ ] **Overwatch rider alerts never reach Telegram.** Found on test order `STRK-TEST-231130`: the 🔴 "🚨 … collected but
  has not delivered — 38 min past the pickup time" message reached WhatsApp but not Telegram. It is the `ops` audience:
  `notify_ops_rider_alert` (`utils_common/waba_utils/wa_senders.py`) sends only through `WALogger.critical()` to the
  numbers in `ordelo_config.overwatch_list`, with no Telegram sink. The restaurant-admin alert (`rest_admins` audience,
  🛵 wording) goes to both channels through `restaurant_notifier.notify(RiderAlert(...))`, so the restaurant side is
  not the gap. Done when the owner decides whether overwatch should also be told on Telegram and, if yes, a Telegram
  sink sits beside `WALogger` (the rider bot's onboarding alert in `channels/telegram/rider/router.py` uses the same
  WhatsApp-only logger) and the ops alert calls it, with tests.
- [ ] **Restaurant admins get no "collected but not delivered" alert on either channel by default.**
  `rider_alert_to_rest_admins_delivery_intervals` defaults to blank (inactive), so only the overwatch message above
  fires for that phase. Done when the owner sets a value (for example `30`) live and checks the 🛵 message arrives on
  WhatsApp and Telegram (runbook step 8b in `dispatch/job_rider_pickup_alerts.sql`), or records that it stays off.
  Live `ordelo_config` values were not checked when this was logged.

## Telegram inbox review (due 15 November 2026)

- [ ] **Decide whether to retire the remaining Telegram inbox protection.** The 22 Oct change limits
  `t_inbox_claim` / `t_inbox_finish` to consequential handlers, but a new protected update still makes
  two HTTPS calls and database writes. Review duplicate-update logs and old `processing` / `failed`
  rows; verify that order, invite and signup RPCs tolerate repeated delivery; and prove a replacement
  dedupe key or equivalent guard prevents repeated rider agent turns (text and job-card taps) and
  duplicate offer-decline cancellation. Done when the evidence and a keep-or-remove decision are
  recorded, with duplicate-delivery tests for every path before removing the RPCs or table.

- Rider offer alerts: correct the `job_create_dispatch.sql` header, which implies open offers block later batches.
- Add `rider_offer_alert` retention to `t_housekeeping()` when housekeeping is scheduled.
- `respond_to_offer()` writes `status_update_dtts` with the app server’s naive local clock; consider using database `now()`.


- WhatsApp and Telegram job cards have no Cancel button; riders request cancellation by typing or by declining an existing offer.
- Protect `dispatch_cancel_before_pickup` against a concurrent pickup with a database-level atomic transition; the existing status check and update are separate.

## Telegram portal links and restaurant dashboard (added 19 Nov 2026)

Built and verified on 19 Nov (offline, isolated SQL and live through the tunnel; see the implementation log in `plans/telegram-portal-links-and-dashboard-plan.md`). The SQL is applied live; the code is NOT deployed.

- [ ] **Deploy order.** restaurant-frontend first (GET-safe activation, settings pages; works with old links), then OrdeloAgent (`/sysadmin`, `/portal`, dashboard_links), then restaurant-agents (date-aware `service_hours`). After OrdeloAgent: republish both default bot menus (`notebooks/telegram/tgram_setup_bot.py`; the rider menu gains `/portal`).
- [ ] **Scoped menu already set.** The live check set the `/sysadmin` scoped menu in the owner's private restaurant-bot chat. Until OrdeloAgent is deployed, production answers `/sysadmin` with the text fallback.
- [ ] **Closed dates gate.** `ordelo_config.REST_DASHBOARD_HOURS_EDITS` is `''` (off). restaurant-agents' old `parse_week` RAISES on a `dates` key, so do not list ELAS/CHKS, BNAT or SFCS until the new restaurant-agents is deployed. Then set it to `all`.
- [ ] **Hidden items on WhatsApp.** The `MENU_API_URL` service (restaurant.byteloop.ai) is not in any connected repo; it does not filter hidden items. The order guard refuses them at order creation; filtering the WhatsApp menu needs the service's owner.
- [ ] **Unrelated, seen during the live check:** `web_order_lookup(...)` is missing on live (UndefinedFunction 500s from the order-lookup feature).
- [ ] **drift_check.py** could not run locally (scratch Postgres has no pgvector/PostGIS). A targeted read-only comparison of all 47 new or changed functions found no drift.

**Owner live testing, 19 Nov.** Passed: Telegram taps (`/manage`, the System dashboard button, `/sysadmin`, the scoped menu, rider `/portal` and `/my_jobs`), My alerts round trip, orders still created, access removal, Reports, menu hide, restaurant-admin updates in sys-admin, and config edits. Two tests are still pending:

- [ ] **Test closed dates (owner live test pending).** Use the STRK test restaurant only. Do not enable ELAS/CHKS, BNAT or SFCS until the new restaurant-agents is deployed: its old reader crashes on a `dates` key and would stop WhatsApp ordering.
  1. Turn editing on: `UPDATE ordelo_config SET config_value = 'STRK' WHERE config_key = 'REST_DASHBOARD_HOURS_EDITS';`
     - Expected: the STRK dashboard's Actions, "Closed dates and hours" card no longer shows "Editing hours … is not switched on" and its Save buttons are enabled.
  2. Close **today** from a time that has already passed: "Close early at…" with a past time, then Save date.
     - Expected: "Closing at HH:MM on <date>." The date is listed under the form.
     - Expected: `restaurant_master.service_hours_json -> 'dates' -> '<today>'` holds today's earlier intervals cut at that time.
     - Expected: sys-admin, Restaurants, STRK, "Recent changes" shows `Hours on date (<today>)` by your number via dashboard.
  3. Open the STRK storefront through the tunnel.
     - Expected: it shows closed, and the next opening skips today.
  4. Try a web checkout with a `TEST3100` basket (or use a checkout tab opened before step 2).
     - Expected: refused with `restaurant_closed`. No `food_order` row is created. In SQL, `create_food_order_with_items` raises `P0C01 order_refused: closed_date`.
     - Also check the message the customer sees: that copy is untested.
  5. Close a future date "Closed all day".
     - Expected: stored as `[["00:00","00:01"]]` and listed as "Closed all day".
     - Expected: the evening before that date stops at midnight (no overnight spill into it).
     - Expected: the day after uses the normal weekly hours.
  6. In sys-admin, Restaurants, STRK, save the weekly hours unchanged.
     - Expected: the `dates` overrides are still there afterwards.
  7. Remove both dates with "Remove", then undo one of the earlier changes from "Recent changes".
     - Expected: after Remove, `service_hours_json` has no `dates` key and the STRK weekly hours are exactly as before.
     - Expected: undoing a change that is no longer current says "changed since".
  - Note for WhatsApp testing (after restaurant-agents is deployed): an overwatch number bypasses venue hours in the restaurant agent (`accepts_new_order` / `is_open`, restaurant-agents `docs/caching_system.md`), but the database order guard has no overwatch bypass. An overwatch tester on a closed date can therefore reach checkout, and then order creation refuses it (`P0C01`). Test with an ordinary customer number to see the normal closed message.
  8. Turn editing off: `UPDATE ordelo_config SET config_value = '' WHERE config_key = 'REST_DASHBOARD_HOURS_EDITS';`
     - Expected: the card shows the "not switched on" note again, and a save answers `disabled` (HTTP 403).
- [ ] **Test WhatsApp `/login` and `/sysadmin` (owner live test pending).** These only exercise the new code when Meta's WhatsApp webhook for the Ordelo number points at the tunnel (`https://rider-agent-test.ordelo.app`), or after OrdeloAgent is deployed. Otherwise the old production code answers.
  1. From an admin number that admins several restaurants (…0754), send `/login`.
     - Expected: one message, "Here's your dashboard. Each link expires in 30 minutes and works once:", then one `Manage <restaurant>: <link>` line per restaurant (no separate CHKS line; ELAS covers it).
     - Expected: each link opens the right restaurant's dashboard, and a second open shows "Session expired".
     - Expected: `auth_sessions` gets one `rest_admin` row per restaurant with `principal_id` = the WhatsApp number.
  2. From a number on no restaurant's admin list, send `/login`.
     - Expected: "You are not a registered restaurant admin." and no `auth_sessions` row.
  3. From an overwatch number, send `/sysadmin`.
     - Expected: "Here's your sys-admin dashboard. Link expires in 30 minutes and works once:" with one `/sys-admin/activate/…` link that opens the system dashboard and works once.
     - Expected: one `sys_admin` row in `auth_sessions`.
  4. From an admin number that is not in overwatch, send `/sysadmin`.
     - Expected: "You are not authorized as sys-admin." and no row.
  5. WhatsApp link previews.
     - Expected: the preview WhatsApp fetches must not use the link up. It is still unused until you tap it (the page only activates on the browser's automatic POST).
- [ ] **pgFormatter breaks some SQL that `format_sql.py` does not catch.** On 19 Nov, formatting the new files changed the JSONB operator `#-` into `# -` (`restaurant_setting_write`) and broke the `%%` escapes inside a dollar-quoted `format()` string (`rest_admin_menu_list`). The guard compares code with whitespace removed, so it missed both; `tests/sql` caught them and the files were restored unformatted. Until `scripts/datamodels/format_sql.py` keeps operator tokens and dollar-quoted bodies intact, do not run it on `restaurant_admin/restaurant_settings.sql`, `restaurant_admin/restaurant_service_hours.sql` or `ordering/menu_item_visibility.sql`, and always run `pytest tests/sql` after formatting. These 11 files are deliberately unformatted: `admin_dashboard/auth_sessions.sql`, `admin_dashboard/rest_admin_reports.sql`, `availability/pauses.sql`, `core/restaurant_master.sql`, `ordering/create_food_order_with_items.sql`, `ordering/menu_item_visibility.sql`, `ordering/order_intake_guard.sql`, `restaurant_admin/admin_roster.sql`, `restaurant_admin/rest_admin_dashboard_alerts.sql`, `restaurant_admin/restaurant_service_hours.sql`, `restaurant_admin/restaurant_settings.sql`. Fifteen other files were already unformatted before this work.

