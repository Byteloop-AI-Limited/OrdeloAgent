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
- [ ] **`fapp_ordelo_agent.py /threads` and `/debug-state-by-thread` query `from_number`,** a column the `thread` table no
  longer has (renamed to `recipient`). Fixed with the R2 debug clean-up.
- [ ] **Race-hardening of rider assignment** (ADR 0011 point 4): `dispatch_response` reads state and writes separately.
  Deferred by D48; Telegram does not make it worse.
- [ ] **Rename `wa_location*`** to channel-neutral names once Telegram locations ship (R5). Cosmetic; touches many files.
- [ ] **`rider_master` holds Telegram ids with RLS off.** Part of the existing row-level-security review; `tuid`/`tcid` are
  now readable with the anon key.
