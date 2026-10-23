# ordelo_datamodels

The database as code for OrdeloAgent: SQL files (tables, functions, triggers, cron jobs) and the Pydantic models that mirror some tables.
The SQL is the authoritative description of the live Supabase database for everything OrdeloAgent owns.

**Start here:** [`ordelo-database-guide.html`](ordelo-database-guide.html) (open in a browser: capability map, flows, object index, cron table, orphans, and a viewer that shows each SQL file with its comments beside the formatted code) or the Markdown twin [`ordelo-database-guide.md`](ordelo-database-guide.md). Both are generated; see below.

## Layout

| Folder | What is in it |
|---|---|
| `core/` | restaurants, customers, riders, menus, `ordelo_config` |
| `ordering/` | order creation, `food_order` additions, web checkout tables |
| `payment/` | payment inbox, authorisation, reconciler |
| `notifications/` | customer events, subscriptions, outbox |
| `delivery/` | `delivery_summary`, options, `init_delivery`, `process_delivery` |
| `dispatch/` | offers, assignment, in-flight job, completion, pickup alerts |
| `takeaway/` | `takeaway_summary`, `init_takeaway` |
| `restaurant_admin/` | accept / decline, pickup time, Ready, +10 / +20, confirmation timeout, receipts and notices |
| `telegram/` | invites, inbox, order cards, paused-admin alert destinations, admin pause RPCs, sent-message ledger, housekeeping |
| `rider_location/` | OwnTracks fixes and events, WhatsApp and Telegram location replies |
| `availability/` | WhatsApp rider shift rule, timed rider/admin pauses, pause-message sweep |
| `agent_threads/` | LangGraph state reads, idle thread jobs |
| `admin_dashboard/` | magic-link sessions, order views, rider payout report |
| `platform/` | HTTP helpers, cron housekeeping, Fly / AWS switches |
| `byteloop_agent/` | Byteloop agent tables and vector search |
| `test_support/` | test helpers and harness scripts (not production) |
| `_orphans/` | live objects nothing calls (owner decides keep or drop) |
| `_archive/` | superseded SQL, never run it |
| `migrations/` | frozen one-off change scripts (history only) |

Python models stay in this folder (`*_pymodel(s).py`); each SQL table file names its model in `PYTHON MODEL`.

## Reading a file

Every file starts with a fixed header: `LIVE CHECK`, `OBJECTS`, `REQUIRES`, `HOW TO RUN`, `SIDE EFFECTS`, `HOW IT FITS`, `LIFECYCLE`,
`CALLED BY`, `PYTHON MODEL`, `SECURITY`, `TESTS`, `GOTCHAS`, `SEE ALSO`. The standard (and why) is in `agents.md`, section
"ordelo_datamodels SQL standard".

## Changing the database

1. Change the owner file (DDL / function body) so it shows the new live shape. Add a migration file only for one-off steps.
2. Update the header, the `CALLED BY` entries and the Python docstrings that point at it.
3. `python scripts/datamodels/format_sql.py` then `python scripts/datamodels/build_guide.py`.
4. After applying to live: `python scripts/datamodels/drift_check.py` (needs `ORDELO_LIVE_DB_URI` and a local `ORDELO_TEST_DB_URI`).
5. `pytest tests/test_datamodels_standard.py`; SQL behaviour tests: `ORDELO_TEST_DB_URI=... pytest tests/sql`.

**R5-R6 status (23 Oct 2026):** live. The migration's VERIFY returned `true / 7 / true / true / 4 / 0`; the app and both command menus are deployed; `drift_check.py` is successful; `job_pause_sweep` is active at `*/5 * * * *` on live (its owner file targets `* * * * *`; moving it is optional, see `docs/to-do.md`); pauses, the `delivery_inflight` guard and the Telegram and WhatsApp delivery flows were checked live by the owner.

## Files that are not hand-edited

`catalog.json`, `ordelo-database-guide.md`, `ordelo-database-guide.html` (built by `scripts/datamodels/build_guide.py`).
Hand-written inputs: `guide_content.json` (capabilities, flows), `external_objects.json` (objects owned elsewhere).
