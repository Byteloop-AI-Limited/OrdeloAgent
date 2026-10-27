# Rider dashboard: implementation and owner rollout

## Rollout status, 27 October 2026

The owner confirmed the database cutover, rider `/my_jobs` registration and coordinated application releases are complete. The dashboard opens directly for riders. The sysadmin payout report issue was resolved in the coordinated backend/frontend release. The procedure below records the original rollout sequence for audit and future reference; it is not a list of remaining owner actions. The migration header records the owner-confirmed application date.

The rider bot `/my_jobs` issues a single-use 30-minute credential to a phone-verified linked Telegram actor. Inactive, suspended, paused and off-shift riders retain financial reads. No graph or delivery action runs. The browser automatically exchanges the link on a same-origin POST and opens the dashboard, setting a secure HttpOnly `__Host-rdash` cookie (60-minute idle / four-hour hard cap, UA-bound). GET/HEAD alone do not consume it, but a link scanner that runs JavaScript can submit the POST. Relinking revokes pending and activated rider credentials atomically.

`ordelo/rider_dashboard.py` is the typed issuance wrapper. Session operations live with `admin_dashboard/auth_sessions.sql`. `admin_dashboard/get_rider_jobs.sql` projects only the session rider's Current (`assigned`, `pickedup`) or Completed jobs, with full-filter totals from one statement snapshot. Only completed payouts are earned; current amounts are expected. Paid date means operations marked the payout paid, not bank-transfer confirmation. The profile projects an already-masked account suffix. Customer addresses, contacts, codes and coordinates never enter this read interface.

The replaced rider HTTP mint, separate summary endpoint and generic rider query proxy are removed. No old payload/cookie decoder, fallback issuance, migration backfill or historical financial repair is provided. `/job` and delivery actions stay in Telegram.

## Read-only live evidence, 26 October 2026

- Database timezone: UTC; no role/database timezone override. All 166 recent joined dispatch/summary comparisons rounded to zero hours difference. Dispatch `dtts` and `paid_dtts` are UTC timestamps without zone; conversion is explicit in SQL. `food_order.order_dtts` is the actual timestamptz order timestamp, projected separately.
- Anonymous/authenticated roles currently have read/write grants on sessions, rider identity/bank applications, dispatches, delivery summaries and orders. The four dependent views are `v_admin_orders`, `v_admin_order_items`, `v_admin_orders_daily`, `v_admin_orders_monthly`; all currently allow anonymous reads. The payout-report function currently allows public execution. These are **observed pre-cutover permissions**, not secured production claims.
- Both public roles also currently have UPDATE on `ordelo_config` and `restaurant_master`. The prepared bundle removes public authority/configuration writes. OrdeloAgent's unsigned WhatsApp ingress was also identified and is now changed in source to require the configured Meta app secret; no live webhook registration was changed.
- Public reads were also verified on `delivery_detail`, `delivery_inflight`, `thread` and the three LangGraph checkpoint tables. Their access-only restrictions are included so job details cannot bypass the rider interface through another source. External thread/checkpoint DDL and graph execution are unchanged.
- Current public security-definer function inventory contained `fly_post`, `job_process_owntracks` and PostGIS extent functions, none projecting private jobs/banking data. Private source grants also stop invoker-function bypasses. Review effective access again at rollout; newly added views/routines require the same check.
- Existing sys-admin payout policy reports stored completed dispatches (excluding its existing dummy rider). No new product/channel/test eligibility rule is introduced. No test payment or payout was created or changed during this implementation.

## Object and caller matrix

| Protected objects | Legitimate caller | Cutover |
| --- | --- | --- |
| `auth_sessions` | Server-only issuers; frontend session modules; authenticated payout guard | Revoke PUBLIC/anon/authenticated; service access; RLS on |
| `rider_master`, `delivery_dispatch`, `delivery_summary` | OrdeloAgent server runtime, service-only rider reads, admin dashboards | Same; OrdeloAgent runtime clients now use its existing service key |
| `delivery_detail`, `delivery_inflight`, `thread`, LangGraph checkpoint tables | Server delivery runtime and database-pool graph persistence | Same; restrict alternate direct reads of the same private jobs without redefining external/library schemas |
| `rider_registrations` | Server admin/onboarding and masked profile read | Same; never return full banking fields to riders |
| `food_order` | OrdeloAgent and restaurant-agent runtime; server frontend projections | Same; restaurant-agent shared PgSetting now uses its existing service key |
| Four admin views | Authenticated frontend dashboard server reads | Explicitly revoke public grants; owner views must not bypass tables |
| `ordelo_config`, `restaurant_master` authority fields | Server configuration and roster administration | Remove public write grants; clients cannot rewrite overwatch membership, login URLs or restaurant admins |
| `get_rider_payout_report` | Authenticated sys-admin report | Service-only execution |
| Rider mint | Trusted Telegram actor only | Removed HTTP route |
| Admin mint | Existing authenticated WhatsApp/Telegram helpers | Removed HTTP mint routes; helpers remain |
| OrdeloAgent WhatsApp ingress | Meta-signed updates | Signature validation enabled with the configured app secret; startup fails if it is missing |
| Payout report/mark-paid HTTP | Authenticated sys-admin browser session via frontend proxy | Actual cookie and original UA forwarded; backend validates role, revocation, expiry, UA and current overwatch membership |
| Thread/debug-state HTTP | Authenticated sys-admin only | Same credential dependency |

## Coordinated manual rollout record

The steps below describe the completed owner rollout sequence. No production SQL, deployment or bot-menu publication was executed by the agent. For a future clean reinstall, use a maintenance window and prepare release artifacts for all three repositories before applying grants; do not leave public access available as a temporary alternate mode.

1. Verify `ordelo_config.RESTAURANT_MENU_APP_URL` is the exact HTTPS frontend origin. Both link issuance and frontend activation use this setting. Ensure the frontend `SUPABASE_SECRET_KEY`, both Python runtimes' existing service keys, and OrdeloAgent's correct WABA app secret are configured. OrdeloAgent now rejects unsigned/forged WhatsApp payloads instead of trusting their supplied sender; verify a real Meta-signed update after deployment. No other restaurant app's webhook setting is changed. Redact `/rider/activate/<token>` from infrastructure access logs and disable analytics on that path. Do not use browser keys for server private reads.
2. Pause public dashboard traffic. Deploy the server-credential caller changes and prepared authenticated HTTP routes in the same maintenance window. Coordinate the restaurant-agent runtime update across its apps according to its constitution. The frontend and OrdeloAgent dashboard feature cannot be exposed until SQL is installed.
3. The one-time SQL bundle is `ordelo_datamodels/migrations/rider_dashboard_cutover.sql`. It was applied by the owner on 2026-10-26. Regeneration with `python scripts/datamodels/rider_dashboard_cutover.py > ordelo_datamodels/migrations/rider_dashboard_cutover.sql` only reads local files and does not connect to a database. The bundle includes the session owner and new jobs functions, but **only the new grant/revocation blocks** from existing table/view/report owners, so unrelated existing definitions are not reapplied. The applied statements remain frozen history below the migration header.
4. The bundle ends with the following standalone credential invalidation statement. Run it once as part of that bundle; do not rerun it after riders start using the new feature. It deliberately makes all old links/cookies unusable; riders request `/my_jobs` again. No payment records change.

```sql
UPDATE public.auth_sessions
SET revoked = true,
    revoked_at = clock_timestamp(),
    revoked_reason = 'rider_dashboard_cutover'
WHERE role = 'rider' AND NOT revoked
RETURNING id, role, revoked;
```

5. Verify effective table/view privileges and function execution as `anon`, `authenticated` and the server role, including attempts through views/invoker routines. Verify missing credentials and wrong-role cookies cannot reach payout/report/debug HTTP routes. Re-test restaurant-admin `/manage` and WhatsApp `/login` and `/sysadmin` through their existing trusted entrypoints. Do not claim safety just from an RLS flag.
6. Deploy/restart both feature applications, run `scripts/datamodels/drift_check.py` using a **separate disposable test URI** and a read-only live URI, and inspect intended drift. The former is reset; a localhost production tunnel is not disposable. Restart/wait out the existing dashboard URL configuration cache when changing origins.
7. Using the setup notebook's existing single `BOT_KEY='rider'`, publish the rider menu. No webhook URL/token change is needed. Inflight chat overrides derive from the new command list; `/help` or `/shift` reconciles an already-existing override.
8. With two authorized rider accounts, verify private command, automatic activation POST, Current/Completed isolation, recorded payout date, replay, expiry, refresh, relink and logout over HTTPS. Check embedded and external browser opening separately because UA binding requires a new link when changing browsers. Do not create real orders or mark real payouts paid for this check. Reopen traffic only after these checks pass.

If permission/caller or deployment checks fail, keep dashboard access closed and fix forward. Do not restore broad anonymous grants as a compatibility mode.

## Verification commands

Backend: focused Telegram/HTTP tests, affected Telegram suite, datamodel standards. SQL: `tests/sql` against the dedicated disposable Postgres only. Frontend: Vitest, TypeScript, lint and production build. Its installed Node version exposes native web storage, so use `NODE_OPTIONS=--no-experimental-webstorage` for the existing jsdom setup. SQL formatting uses pgFormatter 5.6 through `scripts/datamodels/format_sql.py --files <changed owner paths>`; generated catalog/guide files come from `scripts/datamodels/build_guide.py`.

`PgSetting.client` is now a server-role client in both Python runtimes. For an anonymous permission inspection, explicitly construct a client with `pg_settings.rest_key`; do not mistake the runtime client for an anonymous client. This does not change the anon-first rule for ad-hoc operations or authorize production writes.

Offline/isolated passing results establish those contracts only. The owner separately confirmed live Telegram registration, database cutover, coordinated releases and working rider access; the sysadmin payout report was subsequently confirmed working after its release fix. These confirmations are owner-reported rollout evidence, not independently re-probed service evidence by this guide update.

## Verification record, 26 October 2026

- **Affected backend:** 504 passed, including real Telegram dispatching, HTTP session guards, current overwatch removal and signed/unsigned WhatsApp ingress.
- **Frontend:** 237 passed across 13 files; TypeScript and lint passed. Production build passed. Existing image-element lint warnings remain. Includes token-confirmation/POST behavior, strict filters, unsafe cursor rejection, payout rendering, stale-response suppression and error-vs-zero behavior.
- **Rider SQL:** 19 passed against the dedicated disposable Postgres. The generated manual bundle itself was executed there, including old-credential invalidation, anonymous table/view/history denial, blocked authority writes, atomic activation, relink revocation, full-filter aggregates beyond 1,000 rows, DST and caller-independent UTC cursors. No production SQL was applied.
- **Datamodel:** 294 structural/guide checks passed. Changed owner SQL passed the repository formatter and SQLFluff. The unrelated untracked `migrations/rider_offer_alerts.sql` points at two absent owner files and prevents the global migration-history check from passing; that work was preserved.
- **Browser:** isolated HTTPS preview with dummy credentials and fixture Supabase responses. Two separate rider contexts passed Current/Completed separation, profile masking, logout and missing-cookie recovery. Styled mobile view inspected; no horizontal overflow at 320px. This is fixture UI evidence, not a live authorization test or real Telegram delivery.
- **Shared restaurant runtime:** changed files passed Ruff and both settings tests. Its broader suite had 462 passes and the existing `apps/bnat/tests/test_bnat_identity.py::test_bnat_identity_is_app_owned` logo expectation failure. Repository-wide Ruff also reports the unrelated undefined `CALLBACK_URL` in `notebooks/update_callback_url.py`.

Broader existing failures left unchanged:

- Full isolated SQL suite: 471 passed; `test_restaurant_notices_script_sql.py::test_stage0_wipes_only_strk_test_rows_in_every_table` and `::test_stage0_copies_the_linked_chat_to_strk_only_once` fail, matching the known fixture-script issues.
- Earlier full backend run: 1701 passed, one skipped; `tests/ordelo_datamodels/test_master_pymodels.py::test_restaurant_master_get_admins_fetches_live_column` expects a live lookup although the unchanged implementation returns cached admins, plus the unrelated migration-history failure above. Subsequent affected checks pass; no green whole-repository claim is made.

Unrelated concurrent dispatch-alert plans/SQL and restaurant-agent worktree changes were not modified. Temporary preview services and the dedicated test database were stopped after verification; no real bot messages, order/payment mutations, production deployments or menu publications were performed.
