# OrdeloAgent to-do

Open items that are known but deliberately not fixed yet. Each entry says where it was found, why it matters and
what "done" looks like. Remove an entry when it is done and say so in the commit message.

## Database findings (live check, 16 Oct 2026)

Found while organising `ordelo_datamodels/` (plan: [`plans/ordelo-database-organisation-plan.md`](../plans/ordelo-database-organisation-plan.md),
evidence: [`plans/ordelo-database-gate1-review.md`](../plans/ordelo-database-gate1-review.md) section B). The owner chose to
record these as follow-ups; the organisation work documents them but does not change live behaviour.

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
- [ ] **Apply or drop the unapplied indexes.** `idx_thread_active_rest_ref_last_access`
  (`migrations/add_stale_thread_dispatch_index.sql`) and the two `rider_location` indexes were never created live.
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
