# pg_cron owns every schedule: rider invite alerts (phase 1) and the customer notifier loop (phase 2)

**Status:** Plan agreed with the owner on 27 Nov 2026 in a design session. Not started. Implements [ADR 0019](../docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md), and the contributor rule is in `agents.md` ("Add scheduled or retried work"). Amends step 2 of [Per-rider Telegram invites](telegram-rider-invites.md). The invite migration is not applied to live yet.

Already done in the design session: the `agents.md` rule, ADR 0019, two `docs/to-do.md` sections ("Moving SQL hook calls to `app_hook_post()`" and "Customer notifier sweeps: move SQL-only steps out of Python") and the WhatsApp Web subsection of the [verification skill](../.claude/skills/verify-test-order-local-setup/SKILL.md).

## 1. Decisions

| # | Decision | Result |
| --- | --- | --- |
| 1 | Scope | One plan in two phases. Phase 1 must be verified before phase 2 starts. |
| 2 | Which job wakes invite alerts | A new dedicated `job_rider_invite_alerts`, every minute (`* * * * *`). It does not piggyback on `job_rider_offer_alerts`. |
| 3 | How SQL calls the app | A new `platform/app_hook_post.sql`, used by the new jobs only. The 17 older functions move when they are next edited (`docs/to-do.md`). `ordelo_post` stays an operator helper. |
| 4 | Customer notifier logic | **Option B**: the Python sweeps stay unchanged and the jobs wake the app every minute. This is a temporary exception to "POST only when due". A-lite and A are in `docs/to-do.md`. |
| 5 | Customer notifier jobs | Three jobs: outbox sweep and web lifecycle sweep every minute; price audit **hourly at :05 (`5 * * * *`), POSTing only when `web_monitor_run` has no row for today's London date** (owner, 27 Nov 2026), so a failed audit is retried within the hour. |
| 6 | Live database writes | Allowed, with the owner's approval at each step (SQL apply, `cron.schedule`, `cron.unschedule`, invite issue). Failure cases run in the isolated `tests/sql` database first. **The phase 2 jobs stay scheduled after the local verification** (owner, 27 Nov 2026; P2-6 resolved). |
| 7 | Overwatch alert evidence | Read WhatsApp Web (the `ByteLoop Ai` chat only) with `agent-desktop`, in addition to database and log evidence. |
| 8 | Live phase 1 | A staged outage on claim 1, the normal path on claim 2, then reopen claim 2's link. |
| 9 | Implementation | Claude agents in Rex panes, each in a git worktree, coordinated from the design thread (section 8). |

## 2. Before and after

```
BEFORE (lifespan, every Gunicorn worker, also any laptop on the production DB)
  asyncio loop 10 s  → invite_alerts.sweep_pending()            (take → WhatsApp → finish)
  asyncio loop 60 s  → customer_notifier.sweep_pending()        (outbox repair + recovery)
                     → web_ordering.lifecycle.sweep()            (expiry, prunes, payment release)
                     → web_ordering.monitoring.sweep()           (daily price audit claim)

AFTER (one schedule, in Postgres, POSTs to the server named in ORDELO_APP_URL)
  job_rider_invite_alerts    * * * * *  → only if due → /rider-hooks/invite-alerts   → invite_alerts.sweep_pending()
  job_customer_outbox_sweep  * * * * *  → always (B)  → /customer-hooks/outbox-sweep → customer_notifier.sweep_pending()
  job_web_lifecycle_sweep    * * * * *  → always (B)  → /web-hooks/lifecycle-sweep  → lifecycle.sweep()
  job_web_price_audit        5 * * * *  → only if due → /web-hooks/price-audit      → monitoring.sweep()
  every job → app_hook_post(path, payload) → http_post
```

`/web-hooks/...` is deliberately not under `/web`. The `/web` router requires the storefront key (`web_hooks.require_key`), which pg_cron does not send. No existing route shadows the new paths, which was checked on 27 Nov. The only path-parameter routes are `/telegram/{bot_slug}/webhook` and `/web/orders/{order_number}…`, and `customer_hooks` (mounted at `/customer-hooks`) has fixed paths only.

## 3. File changes

| File | Change | Phase |
| --- | --- | --- |
| `ordelo_datamodels/platform/app_hook_post.sql` | **new**: the shared seam between SQL and the app | shared (P1) |
| `ordelo_datamodels/telegram/t_rider_invites.sql` | **new** canonical file for the rider invite RPCs (moved from the migration) | P1 |
| `ordelo_datamodels/telegram/job_rider_invite_alerts.sql` | **new** job | P1 |
| `ordelo_datamodels/telegram/t_invites.sql` | updated to the post-migration table shape (columns, constraints, indexes, RLS) and the admin functions the migration redefines | P1 |
| `ordelo_datamodels/telegram/t_rider_onboarding.sql` | updated with `t_rider_phone_digits`, `t_rider_link`, `t_rider_choices`, `t_rider_set_invite_profile`, `t_rider_set_profile`, `t_rider_profile` from the migration | P1 |
| `ordelo_datamodels/core/rider_master.sql` | add `invite_profile_update_id` | P1 |
| `ordelo_datamodels/restaurant_admin/admin_roster.sql`, `restaurant_admin/restaurant_order_decision.sql`, `telegram/t_order_alerts.sql`, `telegram/t_admin_pauses.sql` | copy the migration's bot-key-filtered versions of `admin_roster_status`, `restaurant_admin_label`, `t_order_admin_phone`, `t_order_card_destinations`, `t_admin_restaurants` | P1 |
| `ordelo_datamodels/migrations/telegram_rider_invites.sql` | header note only (schedule is pg_cron, canonical file names) | P1 |
| `ordelo_datamodels/notifications/job_customer_outbox_sweep.sql` | **new** job | P2 |
| `ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql` | **new** job | P2 |
| `ordelo_datamodels/ordering/job_web_price_audit.sql` | **new** job | P2 |
| `watomation/routers/sweep_hooks.py` | **new** thin router for all four cron-woken hooks | P1 adds 1 route, P2 adds 3 |
| `watomation/fapp_ordelo_agent.py` | remove both lifespan loops, include `sweep_hooks` | P1 (invite loop), P2 (customer loop) |
| `channels/telegram/rider/invite_alerts.py` | delete `run_sweeper`, add a claim log line | P1 |
| `channels/telegram/rider_invites.py` | docstring points at `telegram/t_rider_invites.sql` | P1 |
| `utils_common/notify/customer_notifier.py` | delete `run_sweeper`, add a dispatch log line, update the docstring | P2 |
| `utils_common/web_ordering/lifecycle.py` | add a release-claim log line, update the docstring | P2 |
| `utils_common/web_ordering/monitoring.py` | add a claim and outcome log line, update the docstring | P2 |
| `tests/sql/minimal_schema.sql` | stubs for `http_set_curlopt` and `http_reset_curlopt`; the `http_post` stub can raise | P1 |
| `tests/sql/test_app_hook_post_sql.py` | **new** | P1 |
| `tests/sql/test_rider_invites_sql.py` | **new**: claim, take, finish and the job | P1 |
| `tests/sql/test_customer_sweep_jobs_sql.py` | **new** | P2 |
| `tests/watomation/routers/test_sweep_hooks.py` | **new** | P1, then extended in P2 |
| `tests/channels/telegram/test_rider_invite_alerts.py` | **new**: `FakeRiderInviteDb` | P1 |
| `tests/watomation/test_no_lifespan_loops.py` | **new** guard for ADR 0019 | P1 |
| `docs/telegram-layer.md` (+ HTML companion) | §6 rows, §7 operations line, change log | P1 |
| `agents.md` "Runtime boundaries" | one line: schedules are pg_cron (ADR 0019) | P2 |
| `ordelo_datamodels/catalog.json`, `ordelo-database-guide.{md,html}` | regenerate with `build_guide.py` | both |
| `docs/releases/pg-cron-schedules-<date>.md` | **new** verification report | both |

## 4. Code changes: shared and phase 1

### 4.1 New: `ordelo_datamodels/platform/app_hook_post.sql`

```sql
-- =============================================================================================
-- ordelo_datamodels/platform/app_hook_post.sql
-- The one way SQL wakes OrdeloAgent: POST JSON to {ORDELO_APP_URL}<path> with a timeout (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md).
-- OBJECTS       fn     app_hook_post(p_path text, p_payload jsonb, p_timeout_secs integer) -> integer
--                   POST p_payload to ORDELO_APP_URL + p_path; return the HTTP status, NULL when the call failed. Never raises.
-- REQUIRES      core/ordelo_config.sql; extension http (pgsql-http, with http_set_curlopt / http_reset_curlopt)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run. No BEGIN/COMMIT.
-- SIDE EFFECTS  One HTTP POST per call; a NOTICE when the answer is not 2xx or the call fails.
-- HOW IT FITS   pg_cron job_*() → app_hook_post('/<area>-hooks/<name>', payload) → thin FastAPI route → BackgroundTasks.
--                 ORDELO_APP_URL decides which server does the work (production, or a local tunnel during tests).
-- LIFECYCLE     none
-- CALLED BY     app_hook_post:
--                 sql       job_rider_invite_alerts(), job_customer_outbox_sweep(), job_web_lifecycle_sweep(), job_web_price_audit()
--                 (older functions still build the URL inline: docs/to-do.md "Moving SQL hook calls to app_hook_post()")
-- PYTHON MODEL  watomation/routers/sweep_hooks.py (the routes it calls)
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_app_hook_post_sql.py
-- GOTCHAS       Falls back to https://agent.ordelo.app when ORDELO_APP_URL is empty, like the inline copies.
--               The curl timeout is reset after a normal call; pg_cron opens a fresh session per run in any case.
-- SEE ALSO      platform/ordelo_post.sql (operator helper, different contract); docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function app_hook_post(p_path text, p_payload jsonb, p_timeout_secs integer) -> integer
--   Build ORDELO_APP_URL (trailing slash trimmed) + '/' + p_path (leading slash trimmed), POST the payload as JSON with a
--   curl timeout of p_timeout_secs (minimum 1), and return the status. Returns NULL instead of raising, so a job's own
--   bookkeeping never rolls back because the app is down. The caller decides what a non-2xx means.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.app_hook_post (p_path text, p_payload jsonb DEFAULT '{}'::jsonb, p_timeout_secs integer DEFAULT 5)
    RETURNS integer
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_base text;
    v_url text;
    v_resp http_response;
BEGIN
    SELECT nullif(btrim(config_value), '') INTO v_base
    FROM public.ordelo_config
    WHERE config_key = 'ORDELO_APP_URL';
    v_url := rtrim(coalesce(v_base, 'https://agent.ordelo.app'), '/') || '/' || ltrim(p_path, '/');
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', greatest(coalesce(p_timeout_secs, 5), 1)::text);
    SELECT * INTO v_resp FROM http_post(v_url, coalesce(p_payload, '{}'::jsonb)::text, 'application/json');
    PERFORM http_reset_curlopt();
    IF v_resp.status IS NULL OR v_resp.status NOT BETWEEN 200 AND 299 THEN
        RAISE NOTICE 'app_hook_post: POST % returned %', v_url, v_resp.status;
    END IF;
    RETURN v_resp.status;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'app_hook_post: POST % failed: %', v_url, SQLERRM;
        RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.app_hook_post (text, jsonb, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.app_hook_post (text, jsonb, integer) TO service_role;

COMMENT ON FUNCTION public.app_hook_post (text, jsonb, integer) IS 'POST p_payload to ORDELO_APP_URL + p_path; return the HTTP status, NULL when the call failed. Never raises.';
```

### 4.2 New: `ordelo_datamodels/telegram/t_rider_invites.sql`

The file has a standard 13-section header. Its body is the migration's lines 256–457 **verbatim**: `t_rider_invite_issue`, `_revoke`, `_claim`, `_alert_take`, `_alert_finish`, the grants and the `COMMENT ON` lines. Header values that matter:

```
-- OBJECTS       fn     t_rider_invite_issue(p_phone text) -> jsonb   (… one line each for revoke, claim, alert_take, alert_finish)
-- REQUIRES      telegram/t_invites.sql; core/rider_master.sql; extension pgcrypto
-- HOW IT FITS   scripts/create_rider_invite.py → t_rider_invite_issue → https://t.me/ByteloopRidersBot?start=ri_…
--               /start ri_… → t_rider_invite_claim (links rider_master and queues the alert in one transaction:
--               t_invites.rider_alert_next_at = now) → pg_cron job_rider_invite_alerts (telegram/job_rider_invite_alerts.sql)
--               → /rider-hooks/invite-alerts → invite_alerts.sweep_pending() → t_rider_invite_alert_take (lease, +2 min)
--               → WhatsApp overwatch → t_rider_invite_alert_finish (accepted | retry +1 min | ambiguous +1 min)
-- LIFECYCLE     invite: pending → claimed | revoked.   alert: pending → sending → accepted | retry | ambiguous (→ sending …)
-- CALLED BY     python    channels/telegram/rider_invites.py: issue, revoke, claim, take_alert, finish_alert
--               python    scripts/create_rider_invite.py (issue)
--               sql       job_rider_invite_alerts() reads the due index only
-- SECURITY      RLS on t_invites; PUBLIC, anon and authenticated revoked; service role only (client_ordelo_service).
-- TESTS         tests/sql/test_rider_invites_sql.py; tests/channels/telegram/test_rider_invite_alerts.py
-- GOTCHAS       take/finish never return invite_code. Transport is at least once: an ambiguous send is retried.
```

The other migration sections go to their owner files, as listed in section 3. Each moved definition must match the migration byte for byte. Check with `diff <(sed -n 'A,Bp' migration) <(sed -n 'C,Dp' owner)` for each block.

### 4.3 New: `ordelo_datamodels/telegram/job_rider_invite_alerts.sql`

```sql
-- =============================================================================================
-- ordelo_datamodels/telegram/job_rider_invite_alerts.sql
-- Every minute: wake OrdeloAgent when a rider invite claim alert is due (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md).
-- OBJECTS       fn     job_rider_invite_alerts() -> boolean
--                   POST /rider-hooks/invite-alerts when any rider alert is due; true when idle or answered 2xx.
-- REQUIRES      telegram/t_rider_invites.sql (t_invites alert columns, t_invites_rider_alert_due_idx); platform/app_hook_post.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  At most one HTTP POST per run, only when something is due. Writes nothing: take/finish own the state.
-- HOW IT FITS   t_rider_invite_claim sets rider_alert_next_at → this job (every minute) → app_hook_post → /rider-hooks/invite-alerts
--                 → invite_alerts.sweep_pending() → t_rider_invite_alert_take / _finish. A failed POST changes nothing.
-- LIFECYCLE     see telegram/t_rider_invites.sql
-- CALLED BY     cron      'job_rider_invite_alerts' * * * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: rider_invite_alerts(); channels/telegram/rider/invite_alerts.py: sweep_pending()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_rider_invites_sql.py
-- GOTCHAS       A row in 'sending' is not due until its lease expires (2 min), so a slow sweep is not woken twice for it.
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
-- =============================================================================================

CREATE OR REPLACE FUNCTION public.job_rider_invite_alerts ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_due integer;
    v_status integer;
BEGIN
    SELECT count(*) INTO v_due
    FROM public.t_invites
    WHERE bot_key = 'rider' AND rider_alert_next_at <= now();   -- t_invites_rider_alert_due_idx
    IF v_due = 0 THEN
        RETURN TRUE;                                               -- nothing due: the app is not called
    END IF;
    -- Keep the status in a variable: `f() BETWEEN a AND b` expands to two calls of f(), so it would POST twice.
    v_status := public.app_hook_post('/rider-hooks/invite-alerts',
        jsonb_build_object('event_type', 'rider_invite_alerts', 'due', v_due));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_rider_invite_alerts () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_rider_invite_alerts () TO service_role;
COMMENT ON FUNCTION public.job_rider_invite_alerts () IS 'Every minute: POST /rider-hooks/invite-alerts when any rider invite claim alert is due.';

-- Active on live: no (owner applies after the local verification).
SELECT cron.schedule('job_rider_invite_alerts', '* * * * *', 'SELECT public.job_rider_invite_alerts()');
-- To stop:    SELECT cron.unschedule('job_rider_invite_alerts');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_rider_invite_alerts') ORDER BY start_time DESC LIMIT 10;
```

### 4.4 New: `watomation/routers/sweep_hooks.py` (phase 1 version)

```python
"""
Thin hooks woken by pg_cron (ADR 0019: Postgres owns every schedule; FastAPI never polls).
    . Each route answers 200 at once and runs one existing sweep in BackgroundTasks. The body is ignored.
    . The sweeps claim their rows in SQL (leases, SKIP LOCKED, per-day claims), so a replayed or forged call only
      runs a sweep early. Like the other SQL-triggered hooks these routes carry no secret.
    . Not under /web: that router requires the storefront key, which pg_cron does not send.
  Routes:
    . POST /rider-hooks/invite-alerts  -> channels/telegram/rider/invite_alerts.sweep_pending()

Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . rider_invite_alerts(): job_rider_invite_alerts() in ordelo_datamodels/telegram/job_rider_invite_alerts.sql via pg_cron 'job_rider_invite_alerts' (every minute)
(end of database objects)
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks
from loguru import logger

router = APIRouter(tags=["sweep-hooks"])


async def _run(name: str, sweep: Callable[[], Awaitable[object]]) -> None:
    try:
        result = await sweep()
        logger.info("sweep[{}]: done result={}", name, result)
    except Exception as exc:  # a failed sweep must not crash the worker; the next cron tick retries
        logger.error("sweep[{}]: failed error_type={}", name, type(exc).__name__)


@router.post("/rider-hooks/invite-alerts", include_in_schema=False)
async def rider_invite_alerts(background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_rider_invite_alerts() in ordelo_datamodels/telegram/job_rider_invite_alerts.sql via pg_cron 'job_rider_invite_alerts' (every minute)
    """
    from channels.telegram.rider.invite_alerts import sweep_pending

    background_tasks.add_task(_run, "rider_invite_alerts", sweep_pending)
    return {"status": "accepted"}
```

The invite error log keeps only the error class, never the exception text. A bearer code must never reach a log (plan `telegram-rider-invites.md`).

### 4.5 `channels/telegram/rider/invite_alerts.py`

```diff
@@
-"""Deliver durable invite claim alerts to the existing WhatsApp overwatch channel."""
+"""Deliver durable invite claim alerts to the existing WhatsApp overwatch channel.
+
+sweep_pending() is woken by pg_cron (job_rider_invite_alerts → POST /rider-hooks/invite-alerts,
+watomation/routers/sweep_hooks.py). There is no in-process loop (ADR 0019).
+"""
@@ async def sweep_pending() -> int:
-    """Drain a bounded batch. A worker crash leaves a recoverable database lease."""
+    """Drain a bounded batch. Called from the cron-woken hook; a crash leaves a recoverable database lease."""
     processed = 0
     for _ in range(20):
         lease = uuid4()
         alert = await rider_invites.take_alert(lease)
         if alert is None:
             break
+        logger.info("telegram[rider]: invite alert update {} claimed by sweep", alert.update_id)
         result, accepted = await _deliver(alert)
@@
         processed += 1
     return processed
-
-
-async def run_sweeper() -> None:
-    while True:
-        try:
-            await sweep_pending()
-        except Exception as exc:
-            logger.error("telegram[rider]: invite alert sweep failed error_type={}", type(exc).__name__)
-        await asyncio.sleep(10)
```

`asyncio` is still used by `_deliver`, so its import stays.

### 4.6 `channels/telegram/rider_invites.py`

```diff
-"""Service-role RPCs defined in ordelo_datamodels/telegram/t_invites.sql.
+"""Service-role RPCs defined in ordelo_datamodels/telegram/t_rider_invites.sql (table: telegram/t_invites.sql).
@@
-  . t_rider_invite_issue (function, ordelo_datamodels/telegram/t_invites.sql): calls
-  . t_rider_invite_revoke (function, ordelo_datamodels/telegram/t_invites.sql): calls
-  . t_rider_invite_claim (function, ordelo_datamodels/telegram/t_invites.sql): calls
-  . t_rider_invite_alert_take (function, ordelo_datamodels/telegram/t_invites.sql): calls
-  . t_rider_invite_alert_finish (function, ordelo_datamodels/telegram/t_invites.sql): calls
+  . t_rider_invite_issue (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
+  . t_rider_invite_revoke (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
+  . t_rider_invite_claim (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
+  . t_rider_invite_alert_take (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
+  . t_rider_invite_alert_finish (function, ordelo_datamodels/telegram/t_rider_invites.sql): calls
```

### 4.7 `watomation/fapp_ordelo_agent.py` (phase 1)

```diff
@@
 from utils_common.notify.customer_notifier import run_sweeper
 from channels.telegram.bots import close_registry, default_registry
-from channels.telegram.rider.invite_alerts import run_sweeper as run_rider_invite_alerts
-from watomation.routers import pause_hooks, rider_offer_alerts, telegram_order_alerts, telegram_webhook, web_hooks
+from watomation.routers import pause_hooks, rider_offer_alerts, sweep_hooks, telegram_order_alerts, telegram_webhook, web_hooks
@@ async def lifespan(app):
     app.state.telegram_bots = default_registry()
     task = asyncio.create_task(run_sweeper())
-    invite_alert_task = asyncio.create_task(run_rider_invite_alerts())
     try:
         yield
     finally:
         task.cancel()
-        invite_alert_task.cancel()
         with suppress(asyncio.CancelledError):
             await task
-        with suppress(asyncio.CancelledError):
-            await invite_alert_task
         await close_registry(app.state.telegram_bots)
@@
 app.include_router(rider_offer_alerts.router)
 app.include_router(pause_hooks.router)  # POST /pause-hooks/sweep (job_pause_sweep, R5-R6)
+app.include_router(sweep_hooks.router)  # pg_cron-woken sweeps (ADR 0019)
```

### 4.8 `ordelo_datamodels/migrations/telegram_rider_invites.sql` (header only, before it is applied)

```diff
--- Current definitions now live in: telegram/t_invites.sql, telegram/t_rider_onboarding.sql, core/rider_master.sql
--- and the restaurant legacy readers named below.
+-- Current definitions now live in: telegram/t_invites.sql, telegram/t_rider_invites.sql, telegram/t_rider_onboarding.sql,
+-- core/rider_master.sql and the restaurant legacy readers named below. Alerts are woken by pg_cron
+-- (telegram/job_rider_invite_alerts.sql, ADR 0019), never by an app loop.
```

### 4.9 Tests (phase 1)

`tests/sql/minimal_schema.sql`:

```diff
 CREATE OR REPLACE FUNCTION public.http_post(uri text, content text, content_type text)
 RETURNS public.http_response LANGUAGE plpgsql AS $$
 DECLARE s int;
 BEGIN
     INSERT INTO public.http_calls (url, body) VALUES (uri, content);
     SELECT status INTO s FROM public.http_stub_status LIMIT 1;
+    IF s < 0 THEN
+        RAISE EXCEPTION 'http stub: connection refused';   -- lets tests exercise the exception path
+    END IF;
     RETURN ROW(s, 'application/json', NULL, '{}')::public.http_response;
 END $$;
+CREATE TABLE IF NOT EXISTS public.http_curlopts (opt text, val text);
+CREATE OR REPLACE FUNCTION public.http_set_curlopt(curlopt text, value text) RETURNS boolean LANGUAGE sql AS $$
+    INSERT INTO public.http_curlopts VALUES (curlopt, value) RETURNING true $$;
+CREATE OR REPLACE FUNCTION public.http_reset_curlopt() RETURNS boolean LANGUAGE sql AS $$
+    DELETE FROM public.http_curlopts RETURNING true $$;
```

Make the two `sql` stubs return a single `true`, for example with `SELECT true` after the DML. The shape above is a sketch.

| Test file | Cases |
| --- | --- |
| `tests/sql/test_app_hook_post_sql.py` | URL with and without the trailing slash; missing or blank `ORDELO_APP_URL` gives the fallback; the body is the JSON payload; returns 200 and 500 as given; the stub raising gives NULL with no exception; the timeout is set (`http_curlopts`) and then reset; grants. |
| `tests/sql/test_rider_invites_sql.py` | Load `telegram/t_invites.sql` and `t_rider_invites.sql` on the minimal schema. A claim queues one due alert, and a replay of the same update queues no second one. `job_rider_invite_alerts()`: nothing due → no POST and true; a due row → exactly one POST to `/rider-hooks/invite-alerts` with `due=1`; a `sending` row with a future `next_at` → no POST; 500 → false with the row unchanged; `rest_admin` rows are never counted. Take and finish: `accepted`, `retry`, `ambiguous`, a stale lease, an expired lease retaken (ambiguous count +1), the accepted merge, and take never returning `invite_code`. |
| `tests/channels/telegram/test_rider_invite_alerts.py` | `FakeRiderInviteDb` copies the take/finish return shapes. Cases: all recipients accepted; one recipient fails, giving `ambiguous`, and the next sweep sends only to the rest; an empty or failing overwatch list gives `retry`; at most 20 per sweep; the claim log line has no code. |
| `tests/watomation/routers/test_sweep_hooks.py` | `POST /rider-hooks/invite-alerts` returns 200 `{"status":"accepted"}` and schedules `sweep_pending` once (monkeypatched). The body is ignored. An exception in the sweep is logged and not raised. |
| `tests/watomation/test_no_lifespan_loops.py` | Parse `watomation/fapp_ordelo_agent.py` with `ast` and fail if `lifespan` contains an `asyncio.create_task` call (after phase 2) or any `while True` loop. Also fail if any module under `channels/`, `utils_common/` or `ordelo/` defines `run_sweeper`. In phase 1, the allowance covers both the customer notifier's `create_task` in `lifespan` and its `run_sweeper` definition in `utils_common/notify/customer_notifier.py`. Phase 2 removes both. |

## 5. Code changes: phase 2

### 5.1 New job files (same header pattern as 4.3)

`ordelo_datamodels/notifications/job_customer_outbox_sweep.sql`:

```sql
-- GOTCHAS       Option B (ADR 0019 exception): POSTs every minute even when nothing is due, because the Python sweep also
--               seeds subscriptions/outbox rows and fails interrupted attempts. docs/to-do.md tracks A-lite / A.
CREATE OR REPLACE FUNCTION public.job_customer_outbox_sweep ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status integer;
BEGIN
    -- Never `app_hook_post(...) BETWEEN …`: BETWEEN evaluates its left side twice (two POSTs).
    v_status := public.app_hook_post('/customer-hooks/outbox-sweep',
        jsonb_build_object('event_type', 'customer_outbox_sweep'));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;
REVOKE ALL ON FUNCTION public.job_customer_outbox_sweep () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_customer_outbox_sweep () TO service_role;
COMMENT ON FUNCTION public.job_customer_outbox_sweep () IS 'Every minute: POST /customer-hooks/outbox-sweep (customer outbox repair and recovery).';
-- Active on live: no.
SELECT cron.schedule('job_customer_outbox_sweep', '* * * * *', 'SELECT public.job_customer_outbox_sweep()');
```

`ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql` is the same, with the hook `/web-hooks/lifecycle-sweep`, `event_type` `web_lifecycle_sweep` and the schedule `* * * * *`. Its header must say **HOW IT FITS: the only code that cancels held web payments** (`web_payment_release`, queued by restaurant decline, no rider and late payment).

`ordelo_datamodels/ordering/job_web_price_audit.sql` uses the hook `/web-hooks/price-audit` and the schedule `5 * * * *` (hourly at :05 UTC, owner decision 27 Nov 2026). Unlike the two option B jobs it has a due check: before calling `app_hook_post` it returns true when `EXISTS (SELECT 1 FROM public.web_monitor_run WHERE run_day = (now() AT TIME ZONE 'Europe/London')::date)`, so only the first run of each London day POSTs. Its GOTCHAS says that a failed audit deletes its claim and is retried by the next hourly run, while a crash mid-audit leaves the claim behind and skips that day (already true before). The status still goes into a variable (see the `app_hook_post.sql` GOTCHAS).

### 5.2 `watomation/routers/sweep_hooks.py` (phase 2 additions)

```diff
   Routes:
     . POST /rider-hooks/invite-alerts  -> channels/telegram/rider/invite_alerts.sweep_pending()
+    . POST /customer-hooks/outbox-sweep -> utils_common/notify/customer_notifier.sweep_pending()
+    . POST /web-hooks/lifecycle-sweep  -> utils_common/web_ordering/lifecycle.sweep()   (WEB expiry, prunes, payment release)
+    . POST /web-hooks/price-audit      -> utils_common/web_ordering/monitoring.sweep()  (one claim per London day)
@@
   . rider_invite_alerts(): job_rider_invite_alerts() in ordelo_datamodels/telegram/job_rider_invite_alerts.sql via pg_cron 'job_rider_invite_alerts' (every minute)
+  . customer_outbox_sweep(): job_customer_outbox_sweep() in ordelo_datamodels/notifications/job_customer_outbox_sweep.sql via pg_cron 'job_customer_outbox_sweep' (every minute)
+  . web_lifecycle_sweep(): job_web_lifecycle_sweep() in ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql via pg_cron 'job_web_lifecycle_sweep' (every minute)
+  . web_price_audit(): job_web_price_audit() in ordelo_datamodels/ordering/job_web_price_audit.sql via pg_cron 'job_web_price_audit' (5 * * * *, only when due)
@@
+@router.post("/customer-hooks/outbox-sweep", include_in_schema=False)
+async def customer_outbox_sweep(background_tasks: BackgroundTasks):
+    """Called by database: job_customer_outbox_sweep() (notifications/job_customer_outbox_sweep.sql), every minute."""
+    from utils_common.notify.customer_notifier import sweep_pending
+
+    background_tasks.add_task(_run, "customer_outbox", sweep_pending)
+    return {"status": "accepted"}
+
+
+@router.post("/web-hooks/lifecycle-sweep", include_in_schema=False)
+async def web_lifecycle_sweep(background_tasks: BackgroundTasks):
+    """Called by database: job_web_lifecycle_sweep() (ordering/job_web_lifecycle_sweep.sql), every minute."""
+    from utils_common.web_ordering.lifecycle import sweep
+
+    background_tasks.add_task(_run, "web_lifecycle", sweep)
+    return {"status": "accepted"}
+
+
+@router.post("/web-hooks/price-audit", include_in_schema=False)
+async def web_price_audit(background_tasks: BackgroundTasks):
+    """Called by database: job_web_price_audit() (ordering/job_web_price_audit.sql), hourly at :05 when today's London audit is due."""
+    from utils_common.web_ordering.monitoring import sweep
+
+    background_tasks.add_task(_run, "web_price_audit", sweep)
+    return {"status": "accepted"}
```

The three sweeps run in separate background tasks. One failing no longer skips the others, as it did in the shared `try` block.

### 5.3 `utils_common/notify/customer_notifier.py`

```diff
@@ (module docstring)
-notify_address handles the two pre-order address hooks, which cannot reference
-food_order yet. sweep_pending recovers unattempted rows, not failed deliveries.
+notify_address handles the two pre-order address hooks, which cannot reference
+food_order yet. sweep_pending recovers unattempted rows, not failed deliveries;
+pg_cron wakes it every minute (job_customer_outbox_sweep → POST /customer-hooks/outbox-sweep,
+watomation/routers/sweep_hooks.py). There is no in-process loop (ADR 0019).
@@ async def sweep_pending() -> int:
         rows = await cur.fetchall()
+    if rows:
+        logger.info("customer notifier: outbox sweep dispatching {} unattempted rows ids={}",
+                    len(rows), [r["id"] for r in rows])
     count = 0
@@
-async def run_sweeper() -> None:
-    """Application-owned 60-second sweep; no new SQL or cron registration."""
-    while True:
-        try:
-            await sweep_pending()
-            from utils_common.web_ordering.lifecycle import sweep
-            await sweep()
-            from utils_common.web_ordering.monitoring import sweep as audit_prices
-            await audit_prices()
-        except Exception as exc:
-            logger.error(
-                "customer notifier: sweep failed error_type={}", type(exc).__name__
-            )
-        await asyncio.sleep(60)
```

Keep the `asyncio` import if other code in the module still uses it. Check with `ruff`.

### 5.4 `utils_common/web_ordering/lifecycle.py`

```diff
 async def sweep():
     """Expire WEB threads, prune rate counters and claim up to ten release jobs.
+
+    Woken every minute by pg_cron (job_web_lifecycle_sweep → POST /web-hooks/lifecycle-sweep). This is the
+    only code that cancels held web payments queued by queue_release() / reject_late().
@@
     for job in jobs:
+        logger.info("web lifecycle: release claimed order={} attempts={}", job["order_number"], job["attempts"])
         await release(job["order_number"], job["attempts"])
```

Add `from loguru import logger` if it is not imported yet.

### 5.5 `utils_common/web_ordering/monitoring.py`

```diff
 async def sweep():
     """Claim and run one price audit per London day across registered restaurants.
+
+    Woken by pg_cron (job_web_price_audit, hourly at :05 → POST /web-hooks/price-audit) when today's London audit is due.
@@
     if not claimed:
+        logger.info("web price audit: day {} already claimed", day)
         return
+    logger.info("web price audit: claimed day {}", day)
```

### 5.6 `watomation/fapp_ordelo_agent.py` (phase 2)

```diff
-from utils_common.notify.customer_notifier import run_sweeper
 from channels.telegram.bots import close_registry, default_registry
@@ async def lifespan(app):
     app.state.telegram_bots = default_registry()
-    task = asyncio.create_task(run_sweeper())
     try:
         yield
     finally:
-        task.cancel()
-        with suppress(asyncio.CancelledError):
-            await task
         await close_registry(app.state.telegram_bots)
```

Remove `suppress` and `asyncio` from the imports only if nothing else in the file uses them. Run `ruff check` (F401).

### 5.7 Tests (phase 2)

| Test file | Cases |
| --- | --- |
| `tests/sql/test_customer_sweep_jobs_sql.py` | Each job POSTs exactly once (assert `count(*) FROM http_calls = 1`, to catch the BETWEEN double call) to its path with its `event_type`, returns true on 200, false on 500 and false when the stub raises, without an exception. Grants are checked. Each file's `cron.schedule` line has the agreed schedule (parse the file text). |
| `tests/watomation/routers/test_sweep_hooks.py` | Three new routes, each scheduling the right sweep. An exception in one does not affect another request. |
| `tests/utils_common/test_customer_notifier.py` | Unchanged behaviour. Add one assert for the new log line when rows exist. |
| `tests/watomation/test_no_lifespan_loops.py` | Remove the phase 1 allowance: `lifespan` has no `create_task`. |

## 6. Verification loop

Each phase runs the same four levels in order. A level must pass before the next starts. Label all evidence as **offline**, **isolated database** or **live local**, following the [verification skill](../.claude/skills/verify-test-order-local-setup/SKILL.md). Never put an invite code or URL, or a full phone number, in a log excerpt, a report or a screenshot.

**Gate rule:** every step marked 🔒 stops and asks the owner, in the verification agent's Rex pane. The step names the exact SQL or command and its rollback. The agent does not continue without a "yes".

### 6.1 Level 1: offline

```zsh
cd <worktree> && source .venv/bin/activate && export PYTHONPATH="$PWD" && envLoad
ruff check .
pytest tests/watomation/routers/test_sweep_hooks.py tests/watomation/test_no_lifespan_loops.py \
       tests/channels/telegram tests/utils_common -q
python scripts/datamodels/build_guide.py && pytest tests/test_datamodels_standard.py -q
```

Pass: everything green, except failures that are already known on `dev`, which must be listed with evidence that they fail without this change.

### 6.2 Level 2: isolated database

Use the `ordelo-sql-test-db` skill: `pytest tests/sql -q`, in full, not only the new files. The moved definitions must leave the existing invite, onboarding, roster, order-card and pause tests green. Pass: green, and the new tests cover each `result` value and each job branch: idle, due, 5xx and exception.

### 6.3 Level 3: live preflight (read-only)

| Check | How | Pass |
| --- | --- | --- |
| Routing and webhooks | `python .claude/skills/verify-test-order-local-setup/scripts/db_evidence.py preflight` | `ORDELO_APP_URL = https://rider-agent-test.ordelo.app`; the rider bot webhook is `…/telegram/rider/webhook` on the test host; `ENABLE_SIMULATE_PAYMENT = true` |
| The running server is this code | `lsof -a -p $(lsof -tiTCP:3100 -sTCP:LISTEN \| head -1) -d cwd`; `git -C <cwd> log -1`; `git -C <cwd> status --short` | The cwd checkout holds the implementation branch (gate G2 in section 8) |
| Server log | `rex ls --json` → session `RunServices` → `rex block ls -s <id> --json` → `rex capture -s <id> -b <uvicorn block> --trim --unwrap` | uvicorn running with no traceback since the reload |
| Extensions | read-only SQL: `SELECT extname, extversion FROM pg_extension WHERE extname IN ('http','pg_cron')` | `http` ≥ 1.3 (has `http_set_curlopt` and `http_reset_curlopt`); `pg_cron` present |
| No name clash | `SELECT jobname, schedule, active FROM cron.job ORDER BY jobname` | none of the four new job names exist; record the full list as the baseline |
| Chrome | `agent-desktop status`; `agent-desktop find --app "Google Chrome" --role radiobutton` | accessibility granted; tabs `WhatsApp` and `Telegram Web – left/right view` present; record which tab is active |
| Rider identity | read-only: `SELECT rider_id, status, town, vehicle_type, phone_verified, tuid IS NOT NULL AS linked, t_username FROM rider_master WHERE rider_id = '447448440754'`. Open the rider window (`co open "https://web.telegram.org/k/#@ByteloopRidersBot"`) and `tg-read` the latest linked-rider reply | the Telegram account in Chrome is the one linked to `447448440754`, or it is unlinked and authorised for that rider. Otherwise **stop**. |
| Rider snapshot | the row above plus open offers or jobs and dashboard sessions, saved to `$SCRATCH/rider-before.json` | saved; no open job for the rider |
| WhatsApp baseline | Select the `WhatsApp` tab, search `ByteLoop Ai`, open that chat, record the text (masked) and time of its last message. Select the previous tab again. | recorded |
| Watcher | `nohup python $SK/db_evidence.py watch 2400 > $SCRATCH/watch.log 2>&1 &` (phase 2) | running |

### 6.4 Level 4, phase 1: live rider invite alerts

| Step | Action | Evidence (all four where they apply: Telegram, `ByteLoop Ai`, RunServices log, database) | Pass |
| --- | --- | --- | --- |
| P1-1 🔒 | Apply **only** these four, in order: `migrations/telegram_rider_invites.sql` (if not applied), `platform/app_hook_post.sql`, `telegram/t_rider_invites.sql`, `telegram/job_rider_invite_alerts.sql` (this schedules the job). The migration already redefines the five admin functions on live. **Never apply the updated owner files whole** (`t_invites.sql`, `t_order_alerts.sql`, `admin_roster.sql`, `t_admin_pauses.sql`, …): they hold unrelated objects, `COMMENT ON` lines and runnable `cron.schedule` lines. They are repo copies proved to match live. Then run `python scripts/datamodels/drift_check.py`. If it cannot run locally (no pgvector/PostGIS, see `docs/to-do.md`), fall back to the targeted read-only comparison used on 19 Nov: `pg_get_functiondef` on live for every function in the four files and the five moved admin functions, diffed against the file text. | `cron.job` row `job_rider_invite_alerts`, `* * * * *`, active. Two ticks in `cron.job_run_details` with `succeeded`. No `/rider-hooks/invite-alerts` line in the log, because nothing is due. | idle job, zero POSTs |
| P1-2 🔒 | `SELECT cron.unschedule('job_rider_invite_alerts')` | row gone from `cron.job` | unscheduled |
| P1-3 🔒 | `python scripts/create_rider_invite.py 447448440754 > $SCRATCH/invite1.url` (never print the file) | `t_invites`: one `pending` rider row for the phone | issued |
| P1-4 | **Claim 1, staged outage.** Open the Telegram Web form of the deep link **without the code ever appearing in a command, log or transcript**: `INV=$(python3 -c 'import sys,urllib.parse as u;c=open(sys.argv[1]).read().strip().rsplit("=",1)[1];print("https://web.telegram.org/k/#?tgaddr="+u.quote(f"tg://resolve?domain=ByteloopRidersBot&start={c}",safe=""))' "$SCRATCH/invite1.url"); co open "$INV" > $SCRATCH/inv-win; unset INV`. Check the chat header is **ByteloopRidersBot**, then press **START** with `agent-desktop` (`find --role button` in that window). The `tgaddr` form is not yet proven. If it does not open the bot with a START button, nothing is claimed. The fallback is a typed `/start <code>` built the same way and sent with `tg-say`, recorded as **diagnostic only** because it does not prove the deep link works in the browser. | Telegram: the linked-rider or profile reply within about 5 s. Log: an invite update handled, with no traceback and no code. Database: the invite is `claimed`, `rider_alert_result = 'pending'`, `rider_alert_next_at <= now()`. Wait 150 s, then check that the log has **no** `/rider-hooks/invite-alerts` line and `ByteLoop Ai` has **no** new message. | the alert waits in Postgres |
| P1-5 🔒 | Re-run the job file's `cron.schedule` line | Within 70 s, the log shows `POST /rider-hooks/invite-alerts` 200, `invite alert update … claimed by sweep` and `sweep[rider_invite_alerts]: done result=1`. Database: `accepted`, `rider_alert_next_at IS NULL`, `rider_alert_accepted` = the overwatch numbers. `ByteLoop Ai`: exactly **one** new message, "ℹ️ - Rider bot: personal invite claimed for …0754 by Telegram @…". | delivered once after the outage |
| P1-6 | Watch for 3 minutes | `job_run_details` shows 3 `succeeded` ticks, with no further POST and no second WhatsApp message | idle again |
| P1-7 🔒 | Issue invite 2: `create_rider_invite.py 447448440754 > $SCRATCH/invite2.url`. Compare it privately with invite 1 (`cmp`). | a different code; one new `pending` row | issued |
| P1-8 | **Claim 2, normal path** (the job is running). Same steps as P1-4. | Within 70 s, one POST, one claim line, `accepted`, and exactly one new `ByteLoop Ai` message. The profile, status, shift and pauses match `$SCRATCH/rider-before.json`, and `phone_verified` is unchanged (same-actor claim). | normal path |
| P1-9 | **Reopen claim 2's link** and press START | Telegram: the normal `start=join` or linked-rider reply, not a claim. Database: `claimed_at` and `rider_claim_update_id` unchanged, no new alert row. After 150 s: no POST and no new WhatsApp message. | no second claim or alert |
| P1-10 | Non-regression | `job_rider_offer_alerts` keeps ticking `succeeded`. `ruff` and the app log show no import error after the reload. The log has no `invite alert sweep failed` line, because the loop is gone. | unchanged |

**Phase 1 cleanup:**
- Revoke any rider invite still pending, through `rider_invites.revoke` 🔒.
- Compare the rider row with `$SCRATCH/rider-before.json` and restore only fields that changed and were expected to stay the same 🔒.
- Check that the rider's dashboard sessions still work, or report that they were revoked.
- Close your windows with `co close`, select the owner's previous tab again, and delete the two URL files.
- Leave `job_rider_invite_alerts` scheduled. It never POSTs when idle.

### 6.5 Level 4, phase 2: live customer sweeps

Production still runs the old in-app loop against the same database, so it can claim a release or an outbox row first. A step passes only when the **local** claim line names the order. If production wins, repeat the step once, then record it as inconclusive.

| Step | Action | Evidence | Pass |
| --- | --- | --- | --- |
| P2-0 | Gate G3 (section 8): the main checkout serves phase 2. The local loop is gone and the routes exist. | `rex capture`: reload clean, with no import error. Do not call the new hooks by hand, because each call runs a real sweep. | ready |
| P2-1 🔒 | Apply `notifications/job_customer_outbox_sweep.sql`, `ordering/job_web_lifecycle_sweep.sql` and `ordering/job_web_price_audit.sql`, then run `drift_check.py` | `cron.job`: three new rows with the agreed schedules. Over 3 minutes, the local log shows **exactly one** `/customer-hooks/outbox-sweep` and one `/web-hooks/lifecycle-sweep` per minute, each followed by `sweep[…]: done`. `job_run_details`: `succeeded`. | one sweep per minute, not three |
| P2-2 | **Payment release.** Place a TEST3100 collection order (`co order Collection --qty 2`), then decline it in the restaurant bot (`co tg-tap $KITCHEN OrdeloRestaurantBot $O 'Decline$'`). | Database: a `web_payment_release` row for `$O`, then `completed_at` set within about 60 s; the `payment_released` customer event. Log: `web lifecycle: release claimed order=$O attempts=1`. Page (`watch-page $STORE 110`): "Order cancelled" and the hold released. | released through cron and the local hook |
| P2-3 | **Customer updates do not regress.** Place a second TEST3100 collection order, Accept with a pickup time, then Ready. | The tracking page moves through accepted, pickup set and ready. `notification_outbox` rows are `sent` (dispatched straight away), and the sweep log does not re-dispatch them. | unchanged |
| P2-4 🔒 | `SELECT public.job_web_price_audit()` once by hand | Log: `POST /web-hooks/price-audit` 200 and either `web price audit: day … already claimed` or `claimed day …`. If claimed, `ByteLoop Ai` shows the audit alert (test orders may be flagged), and `web_monitor_run` has today's row. | hook and claim work |
| P2-5 | Isolation | Log: no `customer notifier: sweep failed` line (the old loop). The `ast` guard test is green. | no loop |
| P2-6 | **Resolved (owner, 27 Nov 2026; decision 6): the three jobs stay scheduled.** After G3 the local server has no loop, so unscheduling would leave nothing sweeping while routing points at local and production is idle-suspended, and web payments would stay held. Do not unschedule after the local check. | `cron.job` still lists `job_customer_outbox_sweep`, `job_web_lifecycle_sweep` and `job_web_price_audit` (`5 * * * *`) | no window without a sweeper |

**Phase 2 cleanup:**
- No STRK order is waiting for a decision.
- Stop the watcher and close your windows, then select the owner's previous tab again.
- Write `docs/releases/pg-cron-schedules-<date>.md` with:
  - each step's evidence and label
  - which code handled the Telegram taps
  - any inconclusive steps
  - the final `cron.job` list compared with the baseline
- Remind the owner to restore routing when they are done.

## 7. Production rollout and rollback

1. **Phase 1.** Commit and merge, then apply the SQL from P1-1 to live, if the local run has not already done so. Then deploy. The invite job is idle until the first claim, so the order doesn't matter beyond "SQL before code".
2. **Phase 2.** The three jobs are already scheduled from P2-1 and stay scheduled (decision 6, P2-6); if the local run did not schedule them, schedule them now (🔒). With routing on production:
   1. Until the deploy, production's old code answers 404 to each POST and its old loop covers the gap. Keep that window short: restore routing and deploy back to back.
   2. Deploy.
   3. Check for 200s in `cron.job_run_details` and the Fly logs. Check that the next web decline is released within a minute.
3. The owner restores `ORDELO_APP_URL` and `RESTAURANT_MENU_APP_URL` after local testing (runbook §7).

Rollback:
- **Phase 1 code:** redeploy the previous image. Queued alerts stay in `t_invites`. Leave the job scheduled, because a POST to old code returns 404 and changes nothing.
- **Phase 2:** redeploy the previous image, which still has the loop, and unschedule the three jobs.
- **Never** bring back a lifespan loop alongside the jobs.

## 8. Implementation with Claude agents in Rex

The design thread acts as **coordinator** and stays small. It writes briefs, starts agents, reads only their short reports and `git diff --stat`, and makes the go/no-go calls. All file reading, editing and test output stays inside the agents' panes. The agents' tabs open in the coordinator's own Rex session, never in `RunServices`, which only holds the servers and is read with `rex capture`. The owner can watch every agent tab in the Rex app and answer gate questions there.

**Gates that need the owner:**

- **G0: commit the starting point.** `dev` holds uncommitted work from several streams, so worktrees would otherwise miss the briefs' inputs. The owner confirms the grouping, then commits, or approves the coordinator committing, on a new branch `feature/telegram-rider-invites`:
  - **Commit A, rider invite work:**
    - `channels/telegram/{callbacks,keyboards,rider_links,rider_invites}.py`
    - `channels/telegram/rider/{router,dashboard,invite_alerts}.py`
    - `channels/telegram/rest_admin/router.py` (the owner confirms it belongs to this stream)
    - `watomation/fapp_ordelo_agent.py`, `watomation/routers/telegram_webhook.py`
    - `ordelo_datamodels/migrations/telegram_rider_invites.sql`
    - `scripts/create_rider_invite.py`
    - `plans/telegram-rider-invites.md`
    - the regenerated `ordelo_datamodels/{catalog.json,ordelo-database-guide.md,ordelo-database-guide.html}`
  - **Commit B, this design session:**
    - `agents.md` (`AGENTS.md` is the same file)
    - `docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md`
    - `docs/to-do.md`, the **whole file**, including the STRK-admin item from another stream, so that G2 cannot conflict on it
    - `.claude/skills/verify-test-order-local-setup/SKILL.md`
    - this plan
  - **Left uncommitted on `dev`, another stream:**
    - `plans/web-storefront-controls-and-audit.md`
    - `ordelo_datamodels/migrations/web_storefront_launch_settings.sql`
    - `docs/releases/verify-test-order-local-setup-2026-11-25.md`

    None of these is touched by this plan, so they carry across a branch switch unchanged.
- **G1:** worktree layout. One worktree, `../OrdeloAgent-pgcron` on branch `feature/pgcron-schedules` (from `feature/telegram-rider-invites`). Phase 1 and phase 2 agents run **one after the other** in it, because both edit `fapp_ordelo_agent.py`, `sweep_hooks.py` and `minimal_schema.sql`. Editing in a worktree keeps half-finished saves away from the server, which reloads on every save in the main checkout. The briefs refer to the plan by its path inside the worktree, which commit B puts there.
- **G2 / G3: put the reviewed code on the server.**
  1. The owner runs `git -C /Users/basavaraj/bloop/OrdeloAgent status --short` and confirms that only the three "left uncommitted" files appear.
  2. The owner runs `git switch feature/pgcron-schedules` in the main checkout. Git carries the three untouched files across and refuses if anything would be overwritten. If it refuses, stop and ask; never stash or reset the owner's work.
  3. Uvicorn reloads once. The verification agent checks the reload in `RunServices` before P1-1 (G2) or P2-1 (G3).
  4. Back out with `git switch dev`.

**Agents:**

| Agent | Rex tab | Starts after | Brief (written to `$SCRATCH/briefs/<name>.md`) | Report (`$SCRATCH/reports/<name>.md`, ≤ 30 lines) |
| --- | --- | --- | --- | --- |
| `impl-p1` | `pgcron-impl-p1` | G0, G1 | Sections 3, 4 and 6.1–6.2 of this plan. Follow `agents.md` and the SQL standard. Commit per logical step on the branch. Do not touch the live database or the main checkout. | files changed, test summary, open questions |
| `review-p1` | `pgcron-review-p1` | impl-p1 report | Run `/code-review` on `feature/telegram-rider-invites..feature/pgcron-schedules` against this plan and ADR 0019. Read-only. | findings ranked by severity |
| `verify-p1` | `pgcron-verify-p1` (cwd: main checkout) | review fixed, G2 | Sections 6.3–6.4. Use the verification skill. Stop at every 🔒 and ask the owner in the pane. | the release report path and pass/fail per step |
| `impl-p2`, `review-p2`, `verify-p2` | `pgcron-*-p2` | phase 1 verified | Sections 5, 6.1, 6.2 and 6.5 | as above |

**Starting and following an agent** (from the coordinator):

```zsh
WT=/Users/basavaraj/bloop/OrdeloAgent-pgcron
git -C /Users/basavaraj/bloop/OrdeloAgent worktree add "$WT" -b feature/pgcron-schedules feature/telegram-rider-invites   # G1
rex window new pgcron-impl-p1 -c "$WT" --focus=false --json -- \
  claude "Read $SCRATCH/briefs/impl-p1.md and carry it out. Write your report to $SCRATCH/reports/impl-p1.md and stop."
# save .block_ids[0] as $B; then, without reading the whole pane into the thread:
rex wait "$B" --for 10m --json            # or poll the report file's existence
rex capture -b "$B" --trim | tail -40     # only when the report is missing or the agent is waiting for input
```

Rules for the coordinator:
- Answer an agent's question by sending text into its pane (`rex send -b "$B" '…'`) only when the answer is already decided in this plan. Questions about gates go to the owner.
- Never let two implementation agents edit the same worktree at once.
- The verification agent is the only one that writes to the live database, and only after the owner says "yes" in its pane.
- After each agent, check its claims with `git -C "$WT" log --oneline` and `git -C "$WT" diff --stat` before starting the next one.

## 9. Definition of done

- **Phase 1:**
  - levels 1–4 pass
  - the release report is written
  - the invite loop is gone
  - `job_rider_invite_alerts` is scheduled on live and idle
  - the docs, guide and cross-references are updated
- **Phase 2:**
  - levels 1–4 pass
  - production is deployed with the three jobs scheduled
  - the `lifespan` holds only client setup
  - the `ast` guard has no allowances
  - the `agents.md` sentence naming `customer_notifier.run_sweeper` as the remaining exception is removed
