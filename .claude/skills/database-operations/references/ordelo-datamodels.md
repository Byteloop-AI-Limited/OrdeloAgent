# Ordelo DataModels: where to look

## Tables and types (SQL)

- Base tables and views: `ordelo_datamodels/*.sql`
- Delivery tables: `ordelo_datamodels/summary.sql`, `ordelo_datamodels/dispatch.sql`, `ordelo_datamodels/inflight.sql`, `ordelo_datamodels/detail.sql`
- Master data: `ordelo_datamodels/masterdata.sql`, `ordelo_datamodels/ordelo_config.sql`, `ordelo_datamodels/waba_es.sql`
- Queue schema + helpers: `ordelo_datamodels/sbase_queues_from_order.sql`

## Functions / RPC / scheduled jobs

- Stored procedures + jobs: `ordelo_datamodels/jobs_n_functions/*.sql`
- Migrations history: `ordelo_datamodels/migrations/`

## Fast schema lookup patterns

- Find a table definition: `rg -n "CREATE\\s+TABLE\\s+<table_name>\\b" ordelo_datamodels`
- Find a function definition: `rg -n "CREATE\\s+OR\\s+REPLACE\\s+FUNCTION\\s+<fn_name>\\b" ordelo_datamodels`
