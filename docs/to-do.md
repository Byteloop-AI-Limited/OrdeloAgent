# OrdeloAgent to-do

Open items that are known but deliberately not fixed yet. Each entry says where it was found, why it matters and
what "done" looks like. Remove an entry when it is done and say so in the commit message.

## Database findings (live check, 16 Oct 2026)

Found while organising `ordelo_datamodels/` (plan: [`plans/ordelo-database-organisation-plan.md`](../plans/ordelo-database-organisation-plan.md),
evidence: [`plans/ordelo-database-gate1-review.md`](../plans/ordelo-database-gate1-review.md) section B). The owner chose to
record these as follow-ups; the organisation work documents them but does not change live behaviour.

- [ ] **URGENT: lock down `fly_config` and rotate the Fly tokens.** `fly_config` holds the Fly API tokens that can stop and
  start production machines (2 rows with tokens on 16 Oct 2026). Live has RLS **off** and default grants, so the
  public anon key can read them through PostgREST. The lock-down in `platform/fly_config.sql` was never applied (it is
  kept commented there). Run `ALTER TABLE public.fly_config ENABLE ROW LEVEL SECURITY;` and
  `REVOKE ALL ON TABLE public.fly_config FROM anon, authenticated;`, then rotate both tokens, then uncomment the two
  statements in the file.

- [ ] **Schedule `job_payment_init_reconciler`.** `migrations/ordelo_agg_r1.sql` says to run it every 2 minutes, but
  `cron.job` has no such job, so payment-init reconciliation is not running. Done when the job is scheduled (or the
  owner records that it is intentionally off) and the job's SQL file shows the live schedule.
- [ ] **Schedule `t_housekeeping`.** Telegram inbox and sent-message retention (`tgram_inbox_retention_days`,
  `tgram_ledger_retention_days`) never runs. Done when the job runs nightly and `telegram/t_housekeeping.sql` shows it.
- [ ] **Create the `t_invites` phone-normalise trigger.** The function `t_invites_normalize_phone()` is live but the
  trigger that calls it is not, so `t_invites.phone_number` is stored as typed. Done when the trigger exists live.
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

Found while planning the Telegram rider bot ([`plans/telegram-rider-bot-plan.md`](../plans/telegram-rider-bot-plan.md)).
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
- Add `rider_offer_alert` retention to `t_housekeeping()` when housekeeping is scheduled. Escalation remains once per order, including after re-dispatch.
