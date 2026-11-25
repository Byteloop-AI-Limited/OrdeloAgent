# OrdeloAgent to-do

Open items that are known but deliberately not fixed yet. Each entry says where it was found, why it matters and
what "done" looks like. Remove an entry when it is done and say so in the commit message.

## Database findings (live check, 16 Oct 2026)

Found while organising `ordelo_datamodels/` (plan: [`plans/ordelo-database-organisation-plan.md`](../plans/ordelo-database-organisation-plan.md),
evidence: [`plans/ordelo-database-gate1-review.md`](../plans/ordelo-database-gate1-review.md) section B). The owner chose to
record these as follow-ups; the organisation work documents them but does not change live behaviour.

- [ ] **URGENT: rotate the Fly tokens.** The `fly_config` lock-down is live (checked 23 Nov 2026: RLS on, anon and
  authenticated get 42501, `fly_idle_suspend()` and `job_fly_idle_suspend` at `*/15` active), but before that the anon key
  could read both tokens (`bnat-agent`, `sfcs-agent`; `updated_at` still July/August 2026). Done when both tokens are
  replaced (`fly tokens create deploy -a <app>`, update the row and `updated_at`, revoke the old token in Fly).

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
- [ ] **Lock down `job_process_owntracks()`.** It is `SECURITY DEFINER` and still executable by PUBLIC/anon/authenticated
  on live. (`fly_post()` was confirmed locked down on 23 Nov 2026 and its file now carries the active `REVOKE`.) Done when
  it is revoked from PUBLIC/anon/authenticated live and its file carries the active `REVOKE`.
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

Built and verified on 19 Nov (offline, isolated SQL and live through the tunnel). The decisions and verification evidence are in [ADR 0017](adr/0017-portal-access-is-decided-per-request-in-sql.md) (portal links) and [ADR 0018](adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md) (dashboard settings, closures, hidden items, reports). The live verification loop is the [verify-test-order-local-setup skill](../.claude/skills/verify-test-order-local-setup/SKILL.md). The SQL is applied live; the code is NOT deployed.

Failures that predate this work (seen 19 Nov; treat any other failure as new):
- `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column`
- `tests/test_datamodels_standard.py::test_header_paths_exist[platform/fly_config.sql]`
- `tests/utils_common/order_management/test_restaurant_decision.py::test_describe[auto_decline-None-auto-declined]`
- `tests/sql/test_restaurant_notices_script_sql.py::test_stage0_*` (2)
- restaurant-agents ruff F821 in `notebooks/update_callback_url.py`

Rollback, if needed after deploy:
1. Stop advertising first: clear the overwatch chats' scoped menus and remove `/sysadmin` from the router. The default menu never had it.
2. Keep `REST_DASHBOARD_HOURS_EDITS` off.
3. If a closed date or hidden item is active, clear the data (Remove / Show) rather than reverting the guard.
4. The audit, milestone and hidden-item tables are additive; keep them.

- [ ] **Deploy order: restaurant-agents left.** Checked 23-24 Nov 2026: restaurant-frontend and OrdeloAgent (`27e6928`) are deployed and both default bot menus are republished (restaurant bot has `/manage`, rider bot has `/portal`). Still to do: commit and deploy restaurant-agents' date-aware `service_hours` (uncommitted on 23 Nov) to `sfcs-agent`, `bnat-agent` and the ELAS/CHKS service.
- [ ] **Closed dates gate.** `ordelo_config.REST_DASHBOARD_HOURS_EDITS` is `''` (off). restaurant-agents' old `parse_week` RAISES on a `dates` key, so do not list ELAS/CHKS, BNAT or SFCS until the new restaurant-agents is deployed. Then set it to `all`.
- [ ] **Hidden items on WhatsApp.** The `MENU_API_URL` service (restaurant.byteloop.ai) is not in any connected repo; it does not filter hidden items. The order guard refuses them at order creation; filtering the WhatsApp menu needs the service's owner.
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

## Menu tables (added 23 Nov 2026)

- [ ] **Fix the stale `bnat_menu` column defaults.** `bnat_menu` was created as a copy of `sfcs_menu`, so `branch_link`
  defaults to `https://sfc-salisbury.co.uk` and `branch_name` to `Salisbury` (and its table comment says "This is a
  duplicate of sfcs_menu"). Every live row sets both explicitly and the ordelo-menu-refresh inserts do too, so nothing is
  wrong today. Done when `ordelo_datamodels/core/menus.sql` and live use BNAT defaults (Orpington and the BNAT site link)
  or drop the defaults, applied with owner approval.

## Web storefront launch (24 Nov 2026)

Active work is tracked in [Web storefront controls and audit alignment](../plans/web-storefront-controls-and-audit.md).

- [ ] **Prepare Strikers for real orders after the test period.** The owner is using STRK for testing.
  Keep its storefront, `dummy` rider town and `TEST3100` item available for that work. At commercial cutover,
  set `restaurant_master.city` to Orpington, agree trading hours and order cutoffs, take the test item off public sale,
  and verify an ordinary STRK delivery goes to Orpington riders.
- [ ] **Verify the payment service before promoting the storefronts.** A colleague is working on it. Confirm explicit
  CRMS, CRDO and STRK merchant routing and check BNAT's live route. Done when each merchant's authorization, correct
  payout, return links, receipt, delivery and collection capture, and decline/no-rider release are proven. Verify
  the corresponding Wren test flow where it is used for launch tests.
- [ ] **Agree and verify delivery pricing.** A colleague is working on the pricing service. Review the shared
  CRMS/CRDO/STRK profile and BNAT's separate profile with them. Done when intended areas, minimums, fees and rider
  payouts are verified with representative local and boundary quotes for each venue.
- [ ] **Confirm staff and rider readiness.** Name the staff covering each venue and the rider cover for each
  launch window. Verify the restaurant's alert, acceptance, pickup-time selection, kitchen receipt and escalation
  flows using the intended channels. Rehearse the per-restaurant web pause and confirm an order already in
  progress remains trackable. Keep confirmation of message delivery separate from successful transport calls.

## Found by the local test order run (25 Nov 2026)

Evidence is in the [25 November report](releases/verify-test-order-local-setup-2026-11-25.md).

- [x] **Retire the checkout session once its order is paid.** Fixed and verified locally on 25 Nov, not yet committed or
  deployed. `web_checkout.resume()` refuses a checkout with a paid order, so the storefront starts a new one; `create()`
  refuses to replay a paid order's key. Deploy OrdeloAgent first; the frontend change is only the message for a stale tab.
- [ ] **Decide whether declined and no-rider orders count in the restaurant dashboard totals.** `v_admin_orders_daily`
  sums gross and "your cut" over every order in `v_admin_orders`, including declined and timed-out ones (STRK on 25 Nov:
  `STRK-MZTY-22` and `STRK-UCBX-23` counted).
- [ ] **Reword the fallback card after an admin accepted.** When an admin taps Accept but picks no pickup time, the card
  says "Auto-accepted (no answer in time)" and the kitchen receipt says "Accepted automatically".
