# Plan: organise and document `ordelo_datamodels/` SQL

Status: **Gate 1 approved 16 Oct 2026; in progress.** Research and gate decisions: [`ordelo-database-gate1-review.md`](ordelo-database-gate1-review.md). Production findings: [`docs/to-do.md`](../docs/to-do.md).
Repo: OrdeloAgent. Branch to create: `chore/db-organisation` (from `dev`, after committing the earlier five-file move).

## 1. Why

The SQL under `ordelo_datamodels/` is meant to be the authoritative description of how the database works:
tables, triggers, RPCs, cron jobs and how they connect to the Python code. Today it can't play that role:

- **Layout.** 80 files sit in four buckets (root DDL, `jobs_n_functions/`, `migrations/`, `misc_sql/`) plus
  two new feature folders. You have to know the flow already to find the file.
- **Duplicates.** 19 objects are defined in more than one file, and the copies differ.
  `create_food_order_with_items` appears in 5 files, `process_delivery` in 2, `job_create_dispatch` in 2
  (one copy is inside `db_config.sql`), and the payment and outbox tables are defined in both a root file and
  `migrations/ordelo_agg_r1.sql`.
- **Drift from live.** A read-only check against the live database (16 Oct) found 192 public objects:
  69 tables, 7 views, 110 functions, 11 triggers, plus 16 `pg_cron` jobs.
  - 57 live objects have no file in this repo.
  - About 6 objects in the repo no longer exist live: `app_config`, `dashboard_sessions`,
    `trigger_delivery_dispatch_whook_bulk`, `trg_app_config_updated`, `trigger_update_timestamp`,
    `expire_wa_location_requests_on_inflight_delete`.
- **Migrations used as definitions.** `migrations/` holds both one-off ALTERs and the only definition of live
  features (`ordelo_agg_r1.sql` and `r3.sql`).
- **Documentation quality varies.** It ranges from the full header in `telegram/create_t_invites.sql` to none at all.

## 2. Decisions (from the grilling session)

| # | Decision |
|---|---|
| Q1 | **The live database is the ground truth.** Claude reads it read-only (catalog plus `pg_get_functiondef`, table DDL, triggers, `cron.job`) from the owner's machine. |
| Q2 | **Capability folders** (list in section 3). |
| Q3 | **Live wins on drift.** The authoritative file gets the live body and keeps its human comments. Losing copies move to `_archive/`. Every changed object is listed in a drift report. |
| Q4 | **Extract, then freeze migrations.** Current definitions move into feature files, and the table DDL is reconciled with live first, so ALTER-added columns, constraints and indexes appear in the CREATE TABLE. Migration files stay in `migrations/` as dated history with a header that points to where the definitions now live. **New rule:** every migration must update the feature DDL in the same change. |
| Q5 | **Owner-object files.** One file per primary table: its DDL, indexes, the triggers on it with their trigger functions, and the small RPCs that enforce that table's rules. One file per scheduled job (`job_<name>.sql`, with its `cron.schedule` inside). Files are named after the primary object with no `create_` prefix (so `telegram/create_t_*.sql` becomes `telegram/t_*.sql`). |
| Q6 | **Cross-table workflows.** Columns, constraints and indexes that a workflow adds move into the owning table's file, with a comment `used by <workflow file>`. The workflow file keeps its RPCs, views and grants, plus a `REQUIRES` line. Every column is defined in exactly one place. |
| Q7 | **The 57 live-only objects are handled in tiers. Nothing is dropped.** (1) Objects used by OrdeloAgent or the frontend are captured from live into their folder. (2) Objects owned by restaurant-agents (`food_order`, `order_item`, `thread` and its RPCs, `reservation`) are not copied: the guide points to the restaurant-agents file and flags any drift. (3) Library-managed objects (LangGraph checkpoints, PostGIS, langchain) are listed only. (4) Backups and legacy objects are listed as **orphan candidates** for the owner to decide on later. |
| Q8 | **Fixed header template** (section 4). Every section is present in every file; a section that doesn't apply says `none`. |
| Q9 | **Inline per-object comments plus `COMMENT ON`** statements in the files. Applying `COMMENT ON` to live is a separate step behind an approval gate. It is the only database write in the plan. |
| Q10 | **Python docstrings in both directions, with no code changes.** (a) Every module that touches the database gets a "Database objects" section. (b) Every FastAPI endpoint that the database calls gets a "Called by database" section. Refactoring into wrapper modules is a logged follow-up. |
| Q11 | **Generated guide, offline tests and a read-only drift script** (section 6). |
| Q12 | **`*_pymodel.py` files stay where they are** (53 importers). They are cross-linked with their table files. |
| Q13 | **Branch with two gates.** Gate 1: catalogue, drift report and move map, before any file changes. Gate 2: before `COMMENT ON` is applied to live. One commit per phase. An independent reviewer runs at the end. |
| Q14 | **The guide has five parts:** a capability map, step-through flows, a searchable object index with a detail panel, a cron table, and a drift/orphans/external tab. The `.md` carries the same content for agents. |
| Q15 | **SQL viewer in the guide.** Every SQL file is embedded at build time. Comment blocks appear as formatted prose beside the code they describe (two columns). Code is highlighted with highlight.js (pgsql grammar, inlined) using a theme where comments are full-contrast. |
| Q16 | **Formatting with pgFormatter.** `pg_format` (committed config) formats every file, including PL/pgSQL bodies. `sqlfluff` (postgres dialect, small rule set) runs as a parse and lint check on the DDL. Semantic safety is checked by loading the files into the throwaway Postgres before and after formatting and comparing the catalog with whitespace ignored. Live functions are **not** re-created just to pick up formatting. |

Existing house rules that still apply:

- SQL for manual runs uses standalone statements, with no `BEGIN`/`COMMIT` wrappers (`agents.md`, 2026-10-02).
- Never delete without explicit approval (database-operations skill).
- The RPC pattern in CLAUDE.md "Database-backed logic" still holds.

## 3. Target layout (provisional, confirmed at Gate 1)

The exact file-by-file map is produced in Phase 1 from the live catalogue.

```
ordelo_datamodels/
  README.md                       folder map + the standard (short; points to the guide)
  ordelo-database-guide.html      generated: map, flows, index, cron, drift, SQL viewer
  ordelo-database-guide.md        generated: same content for agents
  catalog.json                    generated: one record per object (file, kind, callers, cron, tests…)
  core/              rider_master, restaurant_master, customer_master, cust_rest_map, ordelo_config,
                     crms_menu (+ live per-restaurant menu tables listed), waba_es, debug_log
  ordering/          create_food_order_with_items, get_next_daily_seq (captured), order_has_test_item,
                     web_session_meta, order_access_grant, web_order_request (from agg r3)
  payment/           payment_event (+ record_payment_authorised), job_payment_init_reconciler
  notifications/     order_notification_subscription, order_customer_event, notification_outbox
  delivery/          delivery_summary (+ kitchen columns, triggers), delivery_detail (+ insert_delivery_detail),
                     delivery_option, delivery_pricing_detail, init_delivery, process_delivery (+ cron),
                     process_restaurant_confirmation (+ cron), job_restaurant_confirmation_timeout,
                     resolve_initial_restaurant_acceptance, cleanup_delivery_order
  dispatch/          delivery_dispatch (+ whook trigger), delivery_inflight (+ whook trigger),
                     job_create_dispatch (+ get_available_riders), job_assign_dispatch (+ assign_accepted_dispatch),
                     dispatch_cancel_before_pickup, dispatch_complete_func, rider_pickup_alert + job_rider_pickup_alerts,
                     notify_missed_dispatches, enquire_shift_availability, get_rider_payout_report
  takeaway/          takeaway_summary (+ trigger), init_takeaway
  rider_location/    rider_location, wa_location (observation + request), job_process_owntracks,
                     job_null_or_outdated_location
  agent_threads/     get_latest_state, job_close_thread, job_terminate_stale_active_threads(_new)
                     (thread table and thread RPCs are owned by restaurant-agents: pointer only)
  restaurant_admin/  restaurant_order_decision, restaurant_ready_adjust_notices, enquire_admin_availability
  telegram/          t_inbox, t_invites, t_order_alerts
  admin_dashboard/   v_admin_orders (+ v_admin_order_items, v_admin_orders_daily captured, indexes), auth_sessions
  platform/          ordelo_post, fly_post, fly_config, job_awsrunner_switch, cron housekeeping
                     (delete-job-run-details)
  migrations/        unchanged history + "current definitions now in:" header
  test_support/      test_restaurant_notices, test_create_t_order_alerts, test_magic_link, clear_dispatch,
                     test_reset_order_and_dispatch, test_reset_takeaway_order, get_ddl_for_table
  _archive/          superseded copies, *_tbd files, deprecated scripts (sbase_queues_from_order, db_config,
                     dispatch_bulk, archive_process_delivery, drop_dispatch_accept_func), ad-hoc queries (elas_stats)
  *_pymodel.py       stay at root (Q12)
```

**How functions are placed (Q5/Q6 interpretation, to confirm at Gate 1):**

- Trigger functions, and small rules that touch only one table, go in that table's file.
- Entry-point or workflow RPCs that span tables (`init_delivery`, `restaurant_order_ready` and similar) get their
  own file, named after the function, in the capability folder of the flow they start.
- Every `pg_cron` job is a `job_*.sql` file, or sits in the file of the function it runs, with its
  `cron.schedule` statement and the live schedule.
- **Live objects with no caller found** (for example `handle_restaurant_confirmation` and `init_delivery_detail`,
  both live although their files say `_tbd`) are captured from live into `_orphans/<area>.sql` (Gate 1 decision D1).
  Nothing is dropped.

## 4. Documentation standard

### 4.1 SQL file header (every file outside `_archive/` and `migrations/`)

```sql
-- =============================================================================================
-- <folder>/<file>.sql
-- <one-line purpose in plain words>
-- =============================================================================================
-- LIVE CHECK    matches live <date> | DRIFT: <what differs> | orphan candidate (no callers found)
-- OBJECTS       table  <name>                      <one line>
--               fn     <name>(<args>) -> <returns>  <one line>
--               trg    <name> <timing> <event> ON <table>
--               view   <name>
--               cron   '<jobname>' <schedule>  -> SELECT <fn>()
-- REQUIRES      <paths of files that must be applied first> | none
-- HOW TO RUN    where (Supabase SQL editor), idempotent?, order, CONCURRENTLY/transaction notes
-- SIDE EFFECTS  tables written; HTTP calls (ordelo_post/fly_post/pg_net -> endpoint); notifications; locks
-- HOW IT FITS   ASCII flow: upstream -> this file's objects -> downstream (tables, triggers, jobs, endpoints)
-- LIFECYCLE     status/state transitions owned here | none
-- CALLED BY     python:   <module>.<function>() -> <object>
--               cron:     '<jobname>'
--               trigger:  <trigger> on <table>
--               frontend: restaurant-frontend <file> .from('<object>')
--               restaurant-agents: <path>
-- PYTHON MODEL  ordelo_datamodels/<x>_pymodel.py <Class> | none
-- SECURITY      RLS on/off, policies, grants/revokes, which client (anon vs service)
-- TESTS         tests/... | none
-- GOTCHAS       non-obvious rules, past incidents | none
-- SEE ALSO      related SQL files, docs/*.md
-- =============================================================================================
```

### 4.2 Inside the file

- A `--` block above every object: what it does, its arguments and return shape (the `result` values for RPCs),
  what it reads and writes, and why it exists if that isn't obvious.
- A trailing comment on every non-obvious column. Every column added by another feature says `-- used by <file>`.
- `COMMENT ON TABLE/FUNCTION/COLUMN …` one-liners at the end of the file, matching the inline text (Q9).
- Statements are idempotent (`CREATE OR REPLACE`, `IF NOT EXISTS`, `DROP … IF EXISTS` before signature changes),
  with no `BEGIN`/`COMMIT` wrappers.
- Formatted with `pg_format` using the repo config. `sqlfluff lint` must pass on the DDL.

### 4.3 Migration file header

```sql
-- MIGRATION (history; do not edit the statements below)
-- Applied to live: <date or "unknown, verified present on <date>">
-- Current definitions now live in: <feature file paths>
-- Purpose: <one line>
```

### 4.4 Python docstrings

- Every module that calls the database gets a `Database objects:` section. Each line is
  `<object> (<kind>) -> ordelo_datamodels/<path>.sql — <what this module does with it>`.
- Every FastAPI route the database calls gets a `Called by database:` section. Each line is
  `<trigger|job> -> <sql file> -> this endpoint`.
- Each pymodel docstring names the table file it mirrors.

## 5. Phases

| Phase | Work | Output | Commit |
|---|---|---|---|
| 0 | Commit the earlier five-file move on `dev`. Create `chore/db-organisation`. Install `pg_format` and `sqlfluff` locally. Write the throwaway-Postgres harness extension (applies all files). | clean starting point | yes |
| 1 | **Research (the most important phase).** (a) Read-only live snapshot: tables, columns, constraints, indexes, views, functions (`pg_get_functiondef`), triggers, RLS, grants, `cron.job`, plus which functions call which (parse bodies for table names, function calls, `ordelo_post`/`net.http_post` targets). (b) Repo inventory of all 80 files. (c) Caller map: Python (`.rpc`, `.table`, raw SQL, FastAPI routes the DB calls), restaurant-frontend `.from()`, restaurant-agents. (d) Drift diff with whitespace and comments normalised. (e) Read `docs/delivery_process.md`, `dispatch_flow.md`, `takeaway_flow.md`, `telegram-layer.md`, `alerts-and-notifications.md` and `pickup_time_logic.md` to check the flows against the live logic. | `catalog.json` draft, drift report, file-by-file move map, flow list | **Gate 1**: owner reviews; no files changed yet |
| 2 | Moves and splits with `git mv` (history kept), following the approved map. Archive the losing copies. Freeze migrations with the header from 4.3. Update every path reference: code, tests (`tests/sql/conftest.py` file list, renamed `t_*`), docs, skills, CLAUDE.md, agents.md and the Project doc copies. Leave `plans/archive/` alone. | new layout; offline and SQL test suites green | yes |
| 3 | Reconcile with live: live bodies and DDL go into the authoritative files (Q3/Q4). Workflow columns move into the table files (Q6). Live-only objects are captured (Q7 tier 1). Load into the throwaway Postgres and prove `catalog(repo) == catalog(live)` for every object the repo owns. | 0 unexplained drift | yes |
| 4 | Format: `pg_format` all files, `sqlfluff lint` the DDL. Semantic check: compare the throwaway-Postgres catalog before and after. | formatted files | yes |
| 5 | Write the SQL documentation: headers (4.1), inline blocks and `COMMENT ON` (4.2), migration headers (4.3), using the Phase 1 understanding. | documented files | yes |
| 6 | Python docstrings in both directions (4.4), and pymodel cross-links. No code changes. | docstrings | yes |
| 7 | Tooling: `scripts/build_db_guide.py` (headers + SQL → `catalog.json`, `.md`, `.html` with the embedded viewer), `scripts/db_drift_check.py` (read-only), and `tests/test_datamodels_standard.py` (section 6). Build the guide. | guide + checks | yes |
| 8 | Standards into `agents.md` and CLAUDE.md (section 7), plus `ordelo_datamodels/README.md`. Update the database-operations skill paths. | rules | yes |
| 9 | **Gate 2**: show the `COMMENT ON` statements. Apply to live only on approval, then rerun the drift check. | live comments | n/a |
| 10 | Independent review: a separate agent that has not seen the work checks a sample of headers against the live catalogue and the caller map, opens the HTML in a browser (every tab, the viewer, light and dark), and runs all suites. Fix what it finds. | review notes | yes |

## 6. Checks that keep it current

`tests/test_datamodels_standard.py` runs offline in the normal `pytest`. It checks that:

- every `.sql` outside `_archive/` and `migrations/` has every header section from 4.1, in order;
- every object is defined in exactly one non-archive, non-migration file;
- every path named in a SQL header, a Python `Database objects:` section or the guide exists;
- every `.rpc("x")` / `.table("x")` in Python refers to an object in `catalog.json` (or on the external list);
- the committed `catalog.json`, `.md` and `.html` match what `build_db_guide.py` produces (stale guide = test failure);
- `pg_format` output equals the committed file.

`scripts/db_drift_check.py` connects to live read-only and reports objects whose normalised definition differs from
the repo, live objects with no file, and repo objects missing live. Run it after any migration and before releases.

## 7. Standards to add to `agents.md` (and align CLAUDE.md rule 2)

1. **Where SQL lives.** One capability folder per business area. One file per primary table (its DDL, indexes,
   triggers, trigger functions and table-only rules). One file per workflow RPC. One `job_*.sql` per cron job,
   holding its `cron.schedule`. No `create_` prefix. `migrations/` is history only.
2. **Live is truth, and the DDL must match it.** A change that alters the database updates the feature file's
   DDL/body in the same commit. A migration may also be added for the one-off steps (ALTER, backfill,
   CONCURRENTLY), but the feature file always shows the current shape. Run `scripts/db_drift_check.py` after
   applying.
3. **Header and inline standard** as in section 4, with every section present.
4. **Cross-references in both directions in the same change:** the SQL `CALLED BY` section, the Python
   `Database objects:` / `Called by database:` sections, and the guide (regenerated).
5. **Formatting:** `pg_format` with the repo config, and `sqlfluff lint` on the DDL.
6. **Regenerate the guide** with `scripts/build_db_guide.py`. Never hand-edit `ordelo-database-guide.*` or `catalog.json`.
7. **Objects owned by other repos** (restaurant-agents) are referenced, never copied.
8. **Nothing is dropped** from live as part of documentation work. Orphan candidates are listed for the owner.

## 8. Guide (`ordelo_datamodels/ordelo-database-guide.html` + `.md`)

- **Capability map:** folders as cards with object counts and one-line purposes.
- **Flows to step through:** delivery order (payment → `init_delivery` → confirmation → `process_delivery`
  → dispatch → inflight → complete), takeaway, restaurant admin (accept, decline, set pickup, ready, adjust),
  Telegram alerts and receipts, rider location. Each step shows the table, trigger, job, HTTP endpoint and Python
  function involved, and links into the viewer.
- **Object index:** search and filter by kind and folder. The detail panel shows the file, live check, run info,
  side effects, callers, cron, tests and pymodel.
- **Cron table:** job, schedule, active flag, function, file.
- **Drift, orphans and external objects:** library objects, restaurant-agents-owned objects, orphan candidates.
- **SQL viewer:** file tree; the header rendered as text; each object's comment as prose beside its code; highlight.js
  pgsql with high-contrast comments; links from the index jump to the line.
- One self-contained file, light and dark themes, modelled on `docs/web-ordering-playground.html`. There is no
  "playground" skill in this session; the existing playground and the frontend-design skill set the style.
- The `.md` has the same sections as headings and tables (no viewer). It links each object to its file.

## 9. Risks and how they're handled

| Risk | Handling |
|---|---|
| A live read hits production load | Read-only transaction, catalog queries only, run once and cached for the session |
| A move breaks imports or tests | `git mv`; the full offline suite plus the SQL suite after Phase 2; `sql_path()` finds files by name |
| Formatting changes behaviour | Throwaway-Postgres catalog compared before and after (Phase 4) |
| Repo bodies differ from live after formatting | The drift check compares normalised text, so formatting alone never shows as drift |
| Removing ALTERs from workflow files breaks the SQL tests | The test harness applies the table files first; `REQUIRES` drives the order |
| Duplicate `notify_missed_dispatches` / `process_delivery` copies hide a live difference | The live body wins (Q3); the losing copy goes to `_archive/` and is listed in the drift report |
| The guide goes stale | The test fails if the regenerated output differs |

## 10. Follow-ups (out of scope)

- Wrapper modules per capability (CLAUDE.md rule 3) to replace the scattered `.table()` calls.
- The owner decides on the orphan candidates (drop or keep).
- Drift between restaurant-agents' own SQL and live (reported, not fixed here).
- Rotate the Supabase DB password. During research a fragment of it appeared in local tool output; it was not
  sent anywhere.
