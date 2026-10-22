# Telegram rider bot R5-R6: handover (22 Oct 2026)

Read first: `plans/telegram-rider-bot-plan.md` (decisions D39-D54; this work is phases R5 and R6), ADR 0013 (+ Amendment 1), `docs/telegram-layer.md`.

## What the plan is

Phases R0-R4 are live. The owner asked for **R5 and R6**, built as one feature, with ONE migration file (`ordelo_datamodels/migrations/rider_telegram_r5_r6.sql`), the live test harness updated (`test_support/test_rider_pauses_and_locations.sql`), and the owner's manual steps listed.

- **R5:** Telegram location replies go through WaLocation (stored source `telegram_current`); rider `/shift`, `/off`, `/on`; `POST /pause-hooks/sweep` + the `job_pause_sweep` schedule; Telegram riders leave the daily 11:00 WhatsApp shift question; the WhatsApp shift "Yes" is refused for non-active riders.
- **R6:** restaurant-admin `/off` and `/on` on the restaurant bot; the last-admin guard (D52); new cards, receipts and notices skip paused admins.

## What is DONE (built and tested, all in the files listed by `git status`)

- SQL: new `availability/rider_shift.sql`, `telegram/t_admin_pauses.sql`, migration and harness; changed `pauses.sql`, `t_order_alerts.sql` (`t_alert_destinations`), `restaurant_ready_adjust_notices.sql`, `enquire_shift_availability.sql`, `rider_location/wa_location.sql`, `job_pause_sweep.sql` (header). Guide and `catalog.json` regenerated with `scripts/datamodels/build_guide.py`.
- Python: `ordelo/rider_shift.py`, `ordelo/pause_notices.py`, `channels/telegram/admin_pauses.py`, `rider/availability.py`, `rider/location.py`, `rest_admin/pauses.py`, `watomation/routers/pause_hooks.py`; changed `ordelo/pauses.py`, `ordelo/wa_location.py`, `ordelo_datamodels/wa_location_pymodels.py`, both bot routers and command menus, `callbacks.py` (`rp1:`, `ap1:`), `keyboards.py`, WhatsApp shift handler/hook, `on_message_wa_handler.py`, `fapp_ordelo_agent.py`.
- Pause taps `rp1:` / `ap1:` use the owner's `process_once` inbox protection (added when merging the "inbox streamlining" commit).
- Tests: new SQL and offline tests for each piece; updated older ones. Results: SQL 358 passed; offline 1553 passed, 8 failed (known baseline, see below).
- Docs updated: plan (status, limits, modules, data model, steps 9-16, evidence), `docs/telegram-layer.md` + `.html`, ADR 0013 Amendment 1, `CONTEXT.md`, `docs/to-do.md`, `docs/live-order-test-harness.md`.

## Local review on the owner's machine (22 Oct 2026)

- The offline suite on this machine: 1560 passed, 1 skipped, 1 existing `RestaurantMaster.get_admins` failure. The affected Telegram, WhatsApp and Ordelo suites after the callback fix: 1057 passed, 1 skipped.
- SQL suite: 358 passed against the dedicated local Postgres 17 database `ordelo_r5r6_drift_scratch` after the owner started PostgreSQL. The cloud copy also reported 358 passes against Postgres 16.
- `drift_check.py`: read-only live snapshot succeeded; the scratch setup stopped at `extension "vector" is not available` before comparing definitions. PostGIS is also absent locally. A focused read-only comparison against the isolated SQL-test database first found old `t_receipt_snapshot()` and `t_notice_targets()` bodies; the owner then applied `restaurant_ready_adjust_notices.sql`. All 14 targeted R5-R6 function definitions now match the isolated test database, and the migration VERIFY returns `true / 7 / true / true / 4 / 0`. Scratch and live ACLs differ by database role/owner, so this is not a full drift result.
- Ruff found 7 F401/F841 warnings in changed Python files; each also exists in `HEAD` (no new lint findings). `pg_format` is unavailable here, so `format_sql.py --check` could not run.
- Both `rp1:` and `ap1:` duplicate taps now get a callback answer even when the inbox skips the repeated update. Dispatcher tests replay the tap after `/on` and prove it cannot restart the pause.
- The generated guide/catalog was rebuilt; its four new files and seven changed entries are R5-R6 SQL or the removal of a scratch `DELETE` from `core/rider_master.sql`. The three named `build/` scratch files were removed.
- The owner reports updating the claude.ai project document `claude/telegram-rider-bot-plan.md`; this local review did not verify the remote copy.

## What remains

1. Full `drift_check.py` remains unrun: the local Postgres lacks pgvector and PostGIS. No extension installation is planned for this documentation task. Run `format_sql.py --check` when pgFormatter is installed.
2. **Owner steps (agents never apply SQL):** the migration's database VERIFY passes after the owner applied `restaurant_ready_adjust_notices.sql`. The owner confirms the R5-R6 app code is deployed and both command menus are republished. Confirm `ORDELO_APP_URL`, then run `job_pause_sweep.sql` to set its live schedule from five minutes to one minute; run the live harness and WhatsApp regression pass. The four PRE-CHECK query results and live test outcomes have not been reported here.

## Steps in plain words (the ones that may be unclear)

- **PRE-CHECK queries:** read-only SELECTs at the top of the migration; they show whether R1-R4 are in place, which Telegram riders will be switched on, how many admins each restaurant has, and which location sources exist. Read them before changing anything.
- **STEP 2 (UPDATE):** sets `is_in_shift = true` for Telegram riders once, because they no longer get the daily question. A rider whose `status` is not exactly `active` still gets no offers.
- **Why apply `job_pause_sweep.sql` after deploying:** the cron job calls `/pause-hooks/sweep`, which only exists in the new code. At the 22 Oct live check the job already existed, active at `*/5 * * * *`; the file changes it to the planned `* * * * *`.
- **`drift_check.py`:** compares the repo's SQL definitions with the live database after applying; run it after the deploy.
- **Re-publishing the command menus:** `notebooks/telegram/tgram_setup_bot.py` with `BOT_KEY = 'rider'` and again with `'rest_admin'`; otherwise `/shift /off /on` don't appear in Telegram's menu.
- **Last-admin guard:** a restaurant admin can pause only if another admin stays unpaused. STRK has one admin, so the owner's own pause there is refused until a second admin phone is added to `restaurant_master.admins` (owner decision; the harness explains it).

## Standing constraints

WhatsApp messages must not change. Agents never apply SQL and never run a DELETE without explicit approval. No `set_webhook` from the app. Secrets are in AWS (`tgram_rider_*`).

## Decisions to keep in mind

- Restaurant-agents validates location source strictly (`whatsapp_current` | `restaurant_confirmation`), so `telegram_current` is mapped on the wire (`wire_source()`); retire when it accepts the new value (`docs/to-do.md`).
- A pause stops only NEW Telegram alerts; existing cards stay live; WhatsApp is untouched.
- Availability is computed from the clock (`is_paused()`); the sweep only closes rows and sends messages, marking them on a 2xx.
