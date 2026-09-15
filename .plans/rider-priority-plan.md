# Rider dispatch prioritisation — `update_rider_priority`

## Context

`rider_master.priority INT NOT NULL DEFAULT 1` has existed since the table was
created and **has never been written by anything** — not by a SQL function, not
by Python, not by any endpoint. The only write in the repo is an ad-hoc
`INSERT` in `notebooks/db_queries/rider_master_updates.sql:37`.

The consequence is a live fairness bug. Which rider gets a dispatch offer is
decided at `ordelo_datamodels/jobs_n_functions/job_create_dispatch.sql:69-70`:

```sql
row_number() OVER (
 PARTITION BY ar.order_number, ar.vehicle_type ORDER BY ar.priority ASC) AS rn
```

Every rider ties at `priority = 1`, and `DISPATCH_BATCH_SIZE_*` defaults to 1,
so Postgres picks an **arbitrary** row for `rn = 1`. In practice the same rider
tends to keep winning offers while others in the same town never get one.
`docs/delivery_process.md:267` (working tree) already documents this honestly:
*"the ranking is effectively an arbitrary tie-break today."*

This change gives `priority` a meaning and a writer: a new
`update_rider_priority()` function that re-ranks riders **within each
(town, vehicle_type) group** so work spreads across the pool — a rider who has
done fewer jobs recently, and who finished longer ago, is offered the next job
first.

Two supporting gaps must close on the way:

- **There is no completion timestamp anywhere in the schema.**
  `dispatch_complete_func.sql:50-52` sets `status = 'completed'` and nothing
  else. On a completed row, `status_update_dtts` still holds the *pickup* time
  (written at `ordelo/agents/rider_agent.py:696-701`), and both
  `notebooks/db_queries/overwatch_views.sql:3` and the `overwatch_view()`
  function (`notebooks/db_queries/overwatch_dashboard.sql:74-82`) read it that
  way. So a new column, not a reuse.
- **`get_available_riders` has no `ORDER BY` at all** — ranking happens entirely
  in the caller's window function.

### Locked decisions (from the grilling session)

| Decision | Choice |
|---|---|
| Meaning of `priority` | Fully derived rank, `1` = next in line. Overwritten every run. |
| Admin manual edit | Allowed, but temporary — the next run overwrites it. No lock flag, no override column. |
| Partition | `(LOWER(town), vehicle_type)` |
| Rank keys | 1. jobs completed in a rolling lookback window **ASC**<br>2. last completion timestamp **ASC**<br>3. deterministic tiebreaker |
| Lookback window | `ordelo_config.RIDER_PRIORITY_LOOKBACK_DAYS`, default **30**. Set to `1` to get "jobs today, then recency". |
| Riders with no history | **First** (`count = 0`, `NULLS FIRST`) — most rested, self-corrects after one job. |
| Completion timestamp | New `delivery_dispatch.completed_dtts`. **Do not touch `status_update_dtts`.** |
| Execution | **Nothing is auto-executed.** No live `cron.schedule`, no bare `select fn();`. The user applies the SQL and registers the cron job manually. |

Accepted trade-off, recorded deliberately: with a 30-day count as the primary
key, a high-volume rider sits behind a low-volume one until the counts converge,
which can take days. `RIDER_PRIORITY_LOOKBACK_DAYS` is the knob for that.

**Recommended cron interval: every 1 minute.** This is a real parameter, not a
detail — see Risk 3. It must be short enough that a rider who *completes* a job
is demoted before the next order arrives (they become eligible again the moment
`dispatch_complete_func` deletes their `delivery_inflight` row), and the whole
point of the feature is lost on an hourly schedule. The `IS DISTINCT FROM`
no-op filter is what makes a 1-minute cadence cheap.

---

## Changes

### 1. New — `ordelo_datamodels/migrations/add_rider_priority.sql`

Header comment stating the run conditions and the "run each statement
individually, outside an explicit transaction" rule (`CREATE INDEX
CONCURRENTLY` cannot run inside one) — the style of
`migrations/add_stale_thread_dispatch_index.sql:1-4`.

- `ALTER TABLE delivery_dispatch ADD COLUMN IF NOT EXISTS completed_dtts TIMESTAMP;`
- Backfill so the first ranking run is not blind:
  ```sql
  UPDATE delivery_dispatch
     SET completed_dtts = COALESCE(status_update_dtts, dtts)
   WHERE status = 'completed'
     AND completed_dtts IS NULL;
  ```
  Two separate approximations to comment, not one:
  1. **Wrong event** — on pre-migration rows `status_update_dtts` is the *pickup*
     time and `dtts` is dispatch creation, so backfilled riders look slightly
     more recent than they were.
  2. **Different clocks** — the `status_update_dtts` branch may have been written
     from Python (`datetime.now(timezone.utc)`, `rider_agent.py:696-701`) or from
     SQL (`CURRENT_TIMESTAMP`, `job_assign_dispatch.sql:83`), while the `dtts`
     branch is always the column default. Since `last_completed_dtts` is rank
     key #2, a systematic skew between branches misorders riders for the first
     lookback window. Acceptable and self-healing, but say so.

  **Run this once, before go-live.** It is *not* safe to re-run afterwards: it
  would stamp any row completed outside `dispatch_complete_func` with that row's
  pickup time. (The `AND completed_dtts IS NULL` clause makes re-running
  harmless only for rows the function already stamped.)
- **One** index, using the literal form `add_stale_thread_dispatch_index.sql`
  uses and `tests/ordelo_datamodels/test_stale_thread_job_sql.py:47` pins:
  ```sql
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_delivery_dispatch_completed_rider
      ON public.delivery_dispatch (completed_dtts, rider_id)
      WHERE status = 'completed';
  ```
  **Column order matters and is `completed_dtts` first.** The only consumer is
  the `recent_jobs` CTE in §2, which filters `completed_dtts > v_cutoff` and
  *then* groups by `rider_id` — it never has a `rider_id` predicate. Leading with
  `rider_id` would leave the window predicate unusable as a leading key and force
  a full scan of the partial index on every tick.
- `rider_master` indexes stay **commented out as deferred** — the table holds on
  the order of a dozen rows; the planner will seq-scan it regardless. Note in
  the comment that `get_available_riders` would want a `WHERE is_in_shift`
  partial index while `update_rider_priority` deliberately scans *all* riders and
  so cannot use it — two indexes, not one.
- Config seed, active and idempotent, per
  `migrations/add_restaurant_confirmation_fields.sql:88-91`:
  ```sql
  INSERT INTO ordelo_config (config_key, config_value, description)
  VALUES ('RIDER_PRIORITY_LOOKBACK_DAYS', '30',
          'Rolling window (days) of completed jobs used to rank rider dispatch priority')
  ON CONFLICT (config_key) DO NOTHING;
  ```
- `cron.schedule('update_rider_priority', '* * * * *', ...)` and its
  `cron.unschedule` counterpart — **commented out**, per
  `process_restaurant_confirmation.sql:96-100`.

### 2. New — `ordelo_datamodels/jobs_n_functions/update_rider_priority.sql`

`update_rider_priority(p_town TEXT DEFAULT NULL, p_vehicle_type TEXT DEFAULT NULL)
RETURNS TABLE(action TEXT) LANGUAGE plpgsql`, with the `/** ... **/` header
format of `job_create_dispatch.sql:1-31`.

```sql
DECLARE
    v_lookback_days INT;
    v_config_value  TEXT;
    v_cutoff        TIMESTAMP;          -- NOT timestamptz; see below
    v_matched       INT;
BEGIN
    -- Serialise overlapping cron runs; released at transaction end.
    IF NOT pg_try_advisory_xact_lock(4242424201) THEN
        RETURN QUERY SELECT 'update_rider_priority already running; skipped.'::text;
        RETURN;
    END IF;

    -- Config read: SELECT INTO + guarded cast, copied from
    -- resolve_initial_restaurant_acceptance.sql:65-77. A COALESCE-of-subselect
    -- CANNOT express this: the regex admits '99999999999', the cast then raises
    -- numeric_value_out_of_range *inside* the subselect, and COALESCE never runs
    -- -- the function would abort on every tick with no fallback. The regex also
    -- excludes '0', which would cast cleanly, set the cutoff to NOW, drive every
    -- count to 0 and silently collapse the ranking to rider_id order.
    SELECT config_value INTO v_config_value
      FROM ordelo_config
     WHERE config_key = 'RIDER_PRIORITY_LOOKBACK_DAYS'
     LIMIT 1;

    IF BTRIM(COALESCE(v_config_value, '')) ~ '^[1-9][0-9]*$' THEN
        BEGIN
            v_lookback_days := BTRIM(v_config_value)::INTEGER;
        EXCEPTION WHEN numeric_value_out_of_range THEN
            v_lookback_days := NULL;
        END;
    END IF;
    v_lookback_days := COALESCE(v_lookback_days, 30);

    -- LOCALTIMESTAMP, not CURRENT_TIMESTAMP: completed_dtts is bare TIMESTAMP,
    -- and CURRENT_TIMESTAMP is timestamptz. Comparing them would implicitly cast
    -- through the session TimeZone, shifting the cutoff by the session offset on
    -- any non-UTC session. LOCALTIMESTAMP keeps both sides on the same type.
    v_cutoff := LOCALTIMESTAMP - make_interval(days => v_lookback_days);

    -- RETURN QUERY + CTE terminating in a SELECT is the repo idiom for surfacing
    -- DML output from a RETURNS TABLE function (job_create_dispatch.sql:42,74-102).
    -- `RETURN QUERY UPDATE ... RETURNING` is not valid plpgsql.
    RETURN QUERY
    WITH recent_jobs AS (
        SELECT dd.rider_id,
               COUNT(*)                 AS jobs_in_window,
               MAX(dd.completed_dtts)   AS last_completed_dtts
          FROM delivery_dispatch dd
         WHERE dd.status = 'completed'
           -- COALESCE covers dispatches completed outside dispatch_complete_func
           -- (hand-run notebook UPDATEs); without it such jobs never count and
           -- the rider stays pinned near priority 1 forever.
           AND COALESCE(dd.completed_dtts, dd.status_update_dtts) > v_cutoff
         GROUP BY dd.rider_id
    ), ranked AS (
        SELECT rm.id,
               DENSE_RANK() OVER (
                 PARTITION BY LOWER(rm.town), rm.vehicle_type
                 ORDER BY COALESCE(rj.jobs_in_window, 0) ASC,
                          rj.last_completed_dtts ASC NULLS FIRST,
                          rm.rider_id ASC NULLS FIRST
               ) AS new_priority
          FROM rider_master rm
          LEFT JOIN recent_jobs rj ON rj.rider_id = rm.rider_id
         WHERE (p_town IS NULL OR LOWER(rm.town) = LOWER(p_town))
           AND (p_vehicle_type IS NULL OR rm.vehicle_type = p_vehicle_type)
    ), applied AS (
        UPDATE rider_master rm
           SET priority = r.new_priority
          FROM ranked r
         WHERE rm.id = r.id
           AND rm.priority IS DISTINCT FROM r.new_priority
        RETURNING rm.id, rm.rider_id, rm.town, rm.vehicle_type, rm.priority
    )
    SELECT 'Rider ' || COALESCE(a.rider_id, '(null rider_id #' || a.id || ')')
           || ' (' || LOWER(a.town) || '/' || a.vehicle_type || ')'
           || ' -> priority ' || a.priority::text AS action
      FROM applied a
     ORDER BY a.priority ASC;
```

Then an **audit line the caller can trust** (see Verification step 5 — without
it, a typo'd town, an already-correct run, and a lock-skip are indistinguishable
from success, and on the *first* run the incoming `priority = 1` rider is
filtered out of `RETURNING` entirely because they already sit at the column
default):

```sql
    SELECT count(*) INTO v_matched FROM rider_master rm
     WHERE (p_town IS NULL OR LOWER(rm.town) = LOWER(p_town))
       AND (p_vehicle_type IS NULL OR rm.vehicle_type = p_vehicle_type);
    RETURN QUERY SELECT format(
        'Matched %s rider(s); lookback %s days; cutoff %s.',
        v_matched, v_lookback_days, v_cutoff)::text;
```

Points that matter:

- **`DENSE_RANK`, not `ROW_NUMBER`, with the sort key ending at `rider_id`.**
  `rider_master` has no `UNIQUE` on `rider_id`, so a rider can own two rows.
  Both carry an identical sort key, so `DENSE_RANK` gives them the same priority
  and ranks stay `1..N` with no gaps over *distinct* riders. This is a
  readability/invariant choice, **not** a correctness requirement — see §4a for
  why the duplicate-dispatch hazard is already closed elsewhere. Do not write a
  test that forbids `ROW_NUMBER`.
- **`NULLS FIRST` is load-bearing and is not the default** (ASC defaults to
  `NULLS LAST`). Dropping it as a "simplification" silently inverts the
  zero-history rule.
- **The count is per `rider_id` across all vehicle types** while the rank
  partitions per `(town, vehicle_type)`. Hypothetical today — seed data keeps one
  row per rider and changes `vehicle_type` by `UPDATE`. Comment it; the fix if it
  becomes real is one line on the join.
- **Rank every rider, including out-of-shift and `status <> 'active'`.**
  An excluded rider keeps whatever priority they last held — possibly `1` — and
  jumps the whole queue the moment they toggle back on shift. Sparse ranks among
  in-shift riders are harmless: only relative order is consumed. (Pre-existing
  and out of scope: `get_available_riders` does not filter `status = 'active'`
  at all.)
- `LOWER(town)` partitioning is mandatory — `job_create_dispatch.sql:53` passes
  `LOWER(dd.town)`. Neither side trims; do not add `BTRIM` to one side only.
- No trailing `select update_rider_priority();`.

### 3. Edit — `ordelo_datamodels/jobs_n_functions/dispatch_complete_func.sql`

```sql
UPDATE delivery_dispatch
   SET status = 'completed',
       -- COALESCE keeps the first completion time if ever called twice
       completed_dtts = COALESCE(delivery_dispatch.completed_dtts, CURRENT_TIMESTAMP)
 WHERE delivery_dispatch.dispatch_id = p_dispatch_id;
```

`status_update_dtts` is deliberately **not** touched — it carries pickup time on
completed rows, and both `overwatch_views.sql:3` and `overwatch_view()`
(`overwatch_dashboard.sql:78`, `ORDER BY status_update_dtts DESC`) depend on it.
Record that in the file's `Side Effects` header block.

> ⚠️ **Applying this file executes a live statement.** It ends at `:76-79` with
> an unconditional `UPDATE delivery_dispatch SET status = 'timedout' WHERE
> status = 'unassigned' AND (current_timestamp - dtts) > interval '30 seconds';`
> below the function body. Pre-existing and out of scope to fix, but since these
> files are applied by hand, comment it out or apply only the
> `CREATE OR REPLACE FUNCTION` block. Same trap at
> `process_restaurant_confirmation.sql:103`.

### 4. Edit — `ordelo_datamodels/jobs_n_functions/job_create_dispatch.sql`

The `RETURNS TABLE(rider_id, priority)` signature is unchanged, so the
load-bearing `GROUP BY` at `:55-60` needs no new columns.

**a. `get_available_riders` gains an `ORDER BY` and a NULL guard** (`:114-138`):

```sql
    SELECT DISTINCT ON (allRiders.rider_id)
           allRiders.rider_id, allRiders.priority
      FROM rider_master allRiders
     WHERE LOWER(allRiders.town) = LOWER(p_town)
       AND allRiders.vehicle_type = p_vehicle_type
       AND allRiders.is_in_shift
       AND allRiders.rider_id IS NOT NULL          -- see below
       AND NOT EXISTS (SELECT 1 FROM ridersToExclude
                        WHERE ridersToExclude.rider_id = allRiders.rider_id)
     ORDER BY allRiders.rider_id, allRiders.priority ASC, allRiders.id ASC;
```

Wrap in an outer `SELECT … ORDER BY priority ASC, rider_id ASC` so the emitted
order is by priority rather than by the `DISTINCT ON` key. No column aliasing is
needed: the live function already selects bare `allRiders.rider_id` /
`allRiders.priority` against OUT params of the same name and runs in production —
plpgsql only resolves `x.y` as a variable when `x` is a block label.

**`AND allRiders.rider_id IS NOT NULL` — a silent order-starvation bug.**
`rider_master.rider_id` is nullable (`masterdata.sql:8`), and a NULL row passes
the `NOT EXISTS` filter because `NULL = x` is never true. It does **not** reach
the `INSERT`: `COUNT(gar.rider_id)` at `:51` ignores NULLs, so the group gets
`rider_count = 0` and is dropped by `WHERE rider_count > 0` at `:84`. The real
failure is worse because it is silent — `rn` is computed in `dispatch_candidates`
(`:69-70`) over **all** `availableRiders` rows *before* that filter, so the NULL
row can take `rn = 1`; with `DISPATCH_BATCH_SIZE_*` at 1, `rn <= batch_size AND
rider_count > 0` then matches nothing, `dispatch_insert` is empty, and
`update_detail_logs` (`:89-98`) immediately flips the detail to
`vehicle_type_timedout` **even though a real rider was available**.

**The `DISTINCT ON` is defence-in-depth, not the fix.** `rider_master` has no
`UNIQUE` on `rider_id` (flagged at `watomation/routers/rider_auth_session.py:33`).
Note that duplicate rows cannot actually produce a double dispatch today: the
`GROUP BY` at `:55-60` includes both `gar.rider_id` and `gar.priority`, so twins
sharing a priority — which `DENSE_RANK` guarantees — collapse to one
`availableRiders` row. `DISTINCT ON` keeps that guarantee local to
`get_available_riders` instead of depending on the caller's `GROUP BY`, and makes
the function safe for direct callers. Trailing `allRiders.id ASC` makes which
twin survives deterministic.

**b. Deterministic batch selection** (`:69-70`):

```sql
row_number() OVER (
  PARTITION BY ar.order_number, ar.vehicle_type
  ORDER BY ar.priority ASC, ar.rider_id_to_dispatch ASC) AS rn
```

The `ORDER BY` added inside `get_available_riders` does **not** make this
deterministic on its own — a function scan's emission order is not something the
outer query may rely on. Both edits are needed. Note the tiebreaker is
lowest-phone-number-wins: deterministic, but not fairness-based, so it should
only ever be reached by riders genuinely tied on rank.

### 5. Edit — `ordelo_datamodels/delivery_pymodels.py`

Add `completed_dtts: Optional[datetime] = None` to `DeliveryDispatch`
(`:114-125`). Not required for correctness (see the impact review) — but the
model already drifts from the table by two columns (`paid_status`, `paid_dtts`);
don't widen the gap to three.

### 6. Docs and domain vocabulary

`docs/delivery_process.md` **has uncommitted working-tree edits** (it is now 801
lines, not 786) — re-read it before editing and do not trust stale line anchors.
In particular `:267` was already rewritten to:

> *"**Applies no `ORDER BY` of its own.** Ranking happens in the caller … Note
> that `rider_master.priority` currently defaults to `1` for every rider and
> nothing in the codebase writes it, so the ranking is effectively an arbitrary
> tie-break today."*

After this change **every clause of that sentence is false**, so it needs a
rewrite, not a tick. Also update: the Configuration Keys table
(`RIDER_PRIORITY_LOOKBACK_DAYS`), the SQL Files Reference
(`update_rider_priority.sql`), and Scheduled Jobs (new row, schedule
`* * * * *`, marked *manual registration*). Bump `Version:` / `Last Updated:`.

Add a **Rider priority** entry to `CONTEXT.md`: a derived, per-(town,
vehicle_type) rank, not a rider attribute — that distinction is what a future
reader will get wrong. Add a one-line comment above `masterdata.sql:14`.
No ADR: this implements an existing column rather than deciding against a
documented alternative.

### 7. Tests — `tests/ordelo_datamodels/test_rider_priority_sql.py`

No live-SQL harness exists (`tests/conftest.py` stubs Supabase wholesale). The
established pattern is static text assertion —
`tests/ordelo_datamodels/test_auto_accept_sql.py`, `test_stale_thread_job_sql.py`.

**Scope every assertion to executable lines, not raw file text.** Strip
comment-only lines first (the same filter
`test_stale_thread_job_is_not_invoked_while_loading_definition` already uses).
Otherwise the tests contradict §2 and §3, which both instruct you to *document*
the very strings some assertions forbid — e.g. §3 asks for a `Side Effects` note
explaining that `status_update_dtts` is untouched, which a whole-file
`assert "status_update_dtts" not in sql` would fail.

Assert, over executable lines only:

- `update_rider_priority.sql` contains `DENSE_RANK()`, `PARTITION BY LOWER(rm.town)`,
  `NULLS FIRST`, `IS DISTINCT FROM`, `LOCALTIMESTAMP`, `pg_try_advisory_xact_lock`,
  `RETURN QUERY`, and `RIDER_PRIORITY_LOOKBACK_DAYS`.
  **Do not** assert `ROW_NUMBER()` is absent — it is a style choice, not a
  correctness constraint (§2).
- `job_create_dispatch.sql` contains `allRiders.rider_id IS NOT NULL`,
  `DISTINCT ON (allRiders.rider_id)`, and
  `ORDER BY ar.priority ASC, ar.rider_id_to_dispatch ASC`.
- `dispatch_complete_func.sql` contains `completed_dtts`.
- The migration contains `ADD COLUMN IF NOT EXISTS completed_dtts`,
  `CREATE INDEX CONCURRENTLY IF NOT EXISTS`, and `(completed_dtts, rider_id)`.
- **Guard test**, per `test_stale_thread_job_sql.py:37-45`: no uncommented
  `select update_rider_priority();` and no uncommented `cron.schedule`. This
  matters more than usual — the files are applied by hand, and five files in the
  repo already execute themselves on load (`process_delivery.sql`,
  `enquire_shift_availability.sql`, `process_restaurant_confirmation.sql`,
  `job_restaurant_confirmation_timeout.sql`, `notify_missed_dispatches_tbd.sql`).

---

## Impact review — adding `delivery_dispatch.completed_dtts`

Traced every reader and writer of `delivery_dispatch`. **The change is
additive-only: one new nullable column, no `status` value, transition, or
webhook payload altered.**

### DeliveryProgress — not affected

`ordelo/delivery_progress.py` backs the import at
`watomation/on_callback_wa_handler.py:40-44`. `check_delivery_progress()` reads
`delivery_inflight` (`:87-100`), then does an **explicit single-column**
`.select("status")` on `delivery_dispatch` (`:111-119`), comparing against
`PICKED_UP_DISPATCH_STATUSES = ("pickedup", "completed")` (`:25`). It never
does `select("*")` and never reflects the column list. All four gated callers —
`admin_adjust_pickup_time`, `admin_collection_ready`, the
`restaurant_pickuptime_adjusted` handler, and the `notify-food-ready-for-pickup`
webhook — resolve through that same enum.

Adjacent but unchanged: `dispatch_complete_func` **deletes the
`delivery_inflight` row**, so a completed order already reports
`NOT_IN_PROGRESS` rather than `PICKED_UP`.

### Everything else, by consumer

| Consumer | Access | Verdict |
|---|---|---|
| `delivery_progress.py:111-119` | `.select("status")` | unaffected |
| `DeliveryDispatch.from_dispatch_id` (`delivery_pymodels.py:126-145`) | `.select("*")` → `cls(**data[0])` | safe — see below |
| `agent_app_handlers.py:428-436` | `.select("*")` → plain dict | extra key inert |
| `sys_admin_auth_session.py:136` (payout) | explicit column list | unaffected |
| `delivery_hooks.py:670`, `rider_agent.py:696/868/1100`, `agent_app_handlers.py:238/260/270` | `.update({...})` named fields | unaffected |
| `delivery_dispatch_whook_statement()` (`dispatch.sql:31-58`) + `dispatch_bulk.sql` twin | `row_to_json(t)` over an **explicit** subquery list | payload byte-identical |
| `notify_missed_dispatches()` (`inflight.sql:120-136`) | `json_build_object` | payload unchanged |
| every `INSERT INTO delivery_dispatch` | all name their columns | unaffected |
| `job_assign_dispatch.sql:61-66` | `SELECT *` in a CTE | inert — downstream CTE names columns |
| `overwatch_view()` (`overwatch_dashboard.sql:74-82`) | `SELECT * FROM delivery_dispatch` in a subquery inside a 38-column `RETURNS TABLE` | inert — outer query projects named columns |
| views | none reference `delivery_dispatch` | unaffected |

**Why the Pydantic `select("*")` is safe, empirically:** `DeliveryDispatch`
declares no `model_config`, so Pydantic v2's default `extra='ignore'` applies —
and the table *already* carries two columns the model does not declare
(`paid_status`, `paid_dtts`, `dispatch.sql:125-128`). That path has been running
against unmodelled columns in production.

### Operational notes

- `ALTER TABLE … ADD COLUMN <nullable, no DEFAULT>` is metadata-only on PG11+.
- The **backfill `UPDATE` is the only statement taking real row locks**. Run once,
  off-peak, before go-live.
- **PostgREST schema cache**: nothing selects or filters `completed_dtts` by name
  over PostgREST, so a stale cache is harmless — but run
  `NOTIFY pgrst, 'reload schema';` if it is ever queried from Python.

### Residual risk

`overwatch_view()` is an in-repo instance of the `SELECT *`-into-a-`RETURNS
TABLE`-function pattern, and it is benign (the outer query projects named
columns). But the repo is not a reliable mirror of production —
`dispatch_accept_func` is called and has no `CREATE` here — so a
production-only function could use the pattern in a way that *is* shape-sensitive
(e.g. `RETURNS SETOF delivery_dispatch`, or `SELECT *` feeding a composite cast).
Verification step 3 greps `pg_proc` for it.

---

## Explicitly not in scope

- **Registering the cron job or running any SQL.** The user does both manually.
- **Wiring `update_rider_priority()` into `job_create_dispatch`.** Would remove
  the staleness window, but wipes a manual admin edit within seconds. One line
  (`PERFORM update_rider_priority();` inside the `IF has_unassigned` guard) if
  ever wanted.
- **A `UNIQUE` constraint on `rider_master.rider_id`**, and a `NOT NULL` on it.
  Both are real bugs needing a data clean-up pass; §4a defends against them.
- **The `job_create_dispatch` multi-vehicle timeout bug** at `:96` — the
  `vehicle_type_timedout` CTE joins on `(order_number, vehicle_type)` but excludes
  on `order_number` alone, so one dispatch suppresses the timeout for the other
  vehicle types. Adjacent; own ticket.
- **Marketing messages** (the other half of the branch name).

## Risks

1. **The repo is not a reliable mirror of production.** Dump the live
   `get_available_riders` / `job_create_dispatch` from `pg_proc` and diff before
   editing.
2. **First run reshuffles every rider**, since all currently sit at `priority = 1`.
   Note the incoming rank-1 rider will *not* appear in the function's `RETURNING`
   output (no change from the default) — the §2 audit line is what makes the run
   legible.
3. **Cron interval is the fairness parameter.** A rider who completes a job is
   eligible again immediately, but keeps rank 1 until the next priority run.
   On a long interval consecutive orders keep landing on the same rider — the
   exact bug this change exists to fix. Use 1 minute.
4. **Staleness within an interval.** Two orders in the same town/vehicle inside
   one tick both see the same ranks and both go to the top rider. Self-heals via
   the inflight exclusion, at ~30s cost on the second order.
5. **A low-count rider who ignores offers pins `priority = 1`.** The window count
   only rises on *completion*, and `get_available_riders` excludes riders
   dispatched **for that order** — not riders who declined or timed out on other
   orders. Mitigation is raising `DISPATCH_BATCH_SIZE_*`, not changing the ranking.
6. **A rider added between runs gets `priority = 1` from the column default** and
   ties the ranked #1, resolved by §4b's lowest-`rider_id` tiebreak. Short cron
   interval keeps the window small.

## Verification

1. `ruff check .` and `pytest tests/ordelo_datamodels/`.
2. Inertness is covered by the §7 guard test — rely on it rather than a raw grep
   (a naive grep hits every `SELECT` in the function body and reads as failure).
3. **Pre-flight against the live DB** (`database-operations` skill):
   ```sql
   -- (a) does production match this repo, and is the SELECT * pattern shape-sensitive?
   SELECT proname FROM pg_proc WHERE prosrc ILIKE '%delivery_dispatch%';
   -- (b) the two rider_master data hazards §4a guards against
   SELECT id, rider_name FROM rider_master WHERE rider_id IS NULL;
   SELECT rider_id, count(*), array_agg(id) FROM rider_master
    GROUP BY rider_id HAVING count(*) > 1;
   -- (c) confirm the session really is UTC (§2 depends on it)
   SHOW TimeZone;
   ```
4. Apply the migration (statements individually, outside a transaction), then
   `update_rider_priority.sql`, `dispatch_complete_func.sql`,
   `job_create_dispatch.sql`. **Before pasting `dispatch_complete_func.sql`,
   comment out its trailing live `UPDATE … SET status='timedout'`** (§3).
5. Dry-run one town. The final audit line must report a non-zero matched count —
   a typo'd town, an already-correct run and a lock-skip all otherwise return
   nothing and read as success:
   ```sql
   SELECT * FROM update_rider_priority('salisbury');
   SELECT rider_id, rider_name, vehicle_type, town, is_in_shift, priority
     FROM rider_master WHERE LOWER(town) = 'salisbury'
    ORDER BY vehicle_type, priority;
   ```
   Assert: priorities run `1..N` with no gaps per (town, vehicle_type) over
   distinct `rider_id` (duplicate rows legitimately share a number); riders with
   no completed jobs in the window are at the top; the most recent completer is
   at the bottom of its group.
6. `SELECT * FROM get_available_riders('<live order>', 'salisbury', 'bicycle');`
   — ascending `priority`, no duplicate `rider_id`, no NULL `rider_id`.
7. End-to-end: place a test order, confirm the offer goes to `priority = 1`;
   complete it; re-run `update_rider_priority()`; confirm that rider moved to the
   back of its group, `completed_dtts` is set, and `status_update_dtts` still
   holds the pickup time.
8. Register the cron job (`* * * * *`), then verify with the introspection query
   at `job_terminate_stale_active_threads.sql:403-436`.
