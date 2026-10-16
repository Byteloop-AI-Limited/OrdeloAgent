# Ordelo DataModels: where to look

## Tables and types (SQL)

- Base tables and views: `ordelo_datamodels/*.sql`
- Delivery tables: `ordelo_datamodels/delivery/delivery_summary.sql`, `ordelo_datamodels/dispatch/delivery_dispatch.sql`, `ordelo_datamodels/dispatch/delivery_inflight.sql`, `ordelo_datamodels/delivery/delivery_detail.sql`
- Master data: `ordelo_datamodels/core/restaurant_master.sql`, `ordelo_datamodels/core/ordelo_config.sql`, `ordelo_datamodels/core/waba_es.sql`
- Queue schema + helpers: `ordelo_datamodels/_archive/sbase_queues_from_order.sql`

## Functions / RPC / scheduled jobs

- Stored procedures + jobs: `ordelo_datamodels/jobs_n_functions/*.sql`
- Migrations history: `ordelo_datamodels/migrations/`

## Fast schema lookup patterns

- Find a table definition: `rg -n "CREATE\\s+TABLE\\s+<table_name>\\b" ordelo_datamodels`
- Find a function definition: `rg -n "CREATE\\s+OR\\s+REPLACE\\s+FUNCTION\\s+<fn_name>\\b" ordelo_datamodels`
