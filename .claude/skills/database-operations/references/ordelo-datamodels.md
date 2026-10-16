# Ordelo DataModels: where to look

The SQL is organised by capability under `ordelo_datamodels/`. Start with `ordelo_datamodels/README.md`, then the generated
guide `ordelo_datamodels/ordelo-database-guide.html` (or `.md`, or `catalog.json` for scripts): capability map, flows, object index,
cron jobs, orphans, and a viewer with every file. Every SQL file begins with a 13-section header (live check, objects, how to run,
side effects, how it fits, lifecycle, callers, Python model, security, tests, gotchas, see also).

## Where things are

- Delivery: `delivery/delivery_summary.sql`, `delivery/init_delivery.sql`, `delivery/process_delivery.sql`, `delivery/delivery_detail.sql`
- Dispatch: `dispatch/delivery_dispatch.sql`, `dispatch/delivery_inflight.sql`, `dispatch/job_create_dispatch.sql`, `dispatch/job_assign_dispatch.sql`
- Takeaway: `takeaway/takeaway_summary.sql`, `takeaway/init_takeaway.sql`
- Master data and config: `core/restaurant_master.sql`, `core/ordelo_config.sql`, `core/rider_master.sql`, `core/customer_master.sql`, `core/waba_es.sql`
- Orders and payment: `ordering/`, `payment/` (`food_order` itself belongs to restaurant-agents; OrdeloAgent's additions are in `ordering/food_order_additions.sql`)
- Restaurant admin actions: `restaurant_admin/`; Telegram layer: `telegram/`
- Cron jobs: each `job_*.sql` (and `delivery/process_delivery.sql`, `restaurant_admin/process_restaurant_confirmation.sql`, ...) holds its `cron.schedule(...)`; the guide's "Cron jobs" tab lists all of them
- Live objects nothing calls: `_orphans/`; superseded SQL (never run): `_archive/`; one-off change history: `migrations/`
- Test helpers: `test_support/`

## Fast lookup

- One object: `python -c "import json;print(json.load(open('ordelo_datamodels/catalog.json'))['objects']['<name>'])"` or search the guide
- A definition by hand: `rg -n "CREATE\s+(OR\s+REPLACE\s+)?(TABLE|FUNCTION|VIEW|TRIGGER)\s+(IF\s+NOT\s+EXISTS\s+)?(public\.)?<name>\b" ordelo_datamodels --glob '!_archive/**' --glob '!migrations/**'`
- Who calls a function: the file's `CALLED BY` header section
- Does a file still match live: `python scripts/datamodels/drift_check.py` (read-only on live; needs a local scratch Postgres)
