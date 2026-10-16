# ordelo_datamodels/_archive

Superseded SQL kept for history. **Nothing here describes the live database and nothing here should be run.**
The current definition of every object is in its capability folder (see `../README.md` and
`../ordelo-database-guide.md`). Files here are not formatted, linted or checked by the standard tests.

| File | Why it is here | Current definition |
|---|---|---|
| `_tbd_handle_restaurant_confirmation.sql` | Old copy of `handle_restaurant_confirmation()`; differs from live (91% similar) | `_orphans/restaurant_admin.sql` (live body, unused) |
| `archive_process_delivery.sql` | Older `process_delivery()` and a duplicate timed-out trigger | `delivery/process_delivery.sql`, `delivery/delivery_summary.sql` |
| `dashboard_sessions.sql` | Table replaced by `auth_sessions`; not live | `admin_dashboard/auth_sessions.sql` |
| `db_config.sql` | `app_config` table (not live) and a stale `job_create_dispatch()` (16% similar to live) | `dispatch/job_create_dispatch.sql` |
| `dispatch_bulk.sql` | Bulk dispatch trigger that is not live; its function body differs from live | `dispatch/delivery_dispatch.sql` |
| `drop_dispatch_accept_func.sql` | Script to drop `dispatch_accept_func`; never run (the function is still live) | `_orphans/dispatch.sql` |
| `init_delivery_detail_tbd.sql` | Old copy of `init_delivery_detail()` | `_orphans/delivery.sql` |
| `notify_missed_dispatches_tbd.sql` | Stale copy of `notify_missed_dispatches()` and the per-order variant | `dispatch/notify_missed_dispatches.sql`, `_orphans/dispatch.sql` |
| `sbase_queues_from_order.sql` | Queue-processing query marked "Deprecated - To Be Deleted" in the file | none |
| `queries/elas_stats.sql` | Ad-hoc ELAS statistics queries; defines no objects | none |
| `jobs_n_functions_result_export.json`, `misc_sql_result_export.json` | Stray query exports | none |

Moved here on 16 Oct 2026 (plan: `plans/ordelo-database-organisation-plan.md`, map: `plans/ordelo-database-gate1-review.md`).
