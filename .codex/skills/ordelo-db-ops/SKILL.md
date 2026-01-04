---
name: ordelo-db-ops
description: Query and operate on the Ordelo Supabase/Postgres database using the project’s `pg_settings.client` / `client_ordelo` object and Ordelo DataModels. Use when Codex needs to select/insert/update/delete rows via Supabase client, run Supabase RPC/stored procedures (e.g. dispatch_* functions, enquire_shift_availability), debug DB state, or edit/create SQL in notebooks/db_queries/*.sql based on ordelo_datamodels/*.sql.
---

# Ordelo Db Ops

## Overview

Use Ordelo’s Supabase/Postgres clients to read or change DB state, and use Ordelo DataModels as the source of truth for table/function names and shapes.

## Repo Pointers (load as needed)

- Tables + functions + jobs (SQL): `ordelo_datamodels/` (see `references/ordelo-datamodels.md`)
- Example ad-hoc SQL (debug ops): `notebooks/db_queries/CommonQueries.sql`
- Supabase client + async pool: `config/pg_setting.py`
- Raw SQL helpers (async pool): `utils_common/db_utils/sbase_pool_ops.py`
- REST helper wrappers (optional): `utils_common/db_utils/sbase_rest_ops.py`

## Environment Setup

Ensure the environment is set up via `run_setup.sh`:

```bash
./run_setup.sh  # First time (requires AWS_SETTINGS_* env vars)
source venv/bin/activate  # Subsequent runs - PYTHONPATH is auto-set
```

## Quick Start (Supabase client)

The Supabase client used across this repo is created from `pg_settings.client` and often aliased as `client_ordelo`:

```py
from config import pg_settings

client_ordelo = pg_settings.client
```

Equivalent import (when you do not need to re-create the client):
```py
from config import client_ordelo
```

Select:

```py
res = (
    client_ordelo.table("delivery_summary")
    .select("*")
    .eq("order_number", order_number)
    .execute()
)
rows = res.data  # list[dict]
```

Insert:

```py
client_ordelo.table("food_order").insert(insert_payload).execute()
# See: utils_common/order_management/order_db_ops_new.py
```

Update:

```py
client_ordelo.table("delivery_dispatch").update({"status": "pickedup"}).eq("dispatch_id", dispatch_id).execute()
```

Delete (always filter tightly):

```py
client_ordelo.table("delivery_option").delete().like("order_number", "WREN-TEST-%").execute()
```

## RPC / Stored Procedures

Call Postgres functions exposed via Supabase RPC:

```py
client_ordelo.rpc("dispatch_cancel_before_pickup", {"p_dispatch_id": dispatch_id}).execute()
```

If the function lives in a non-`public` schema, use `.schema(...)`:

```py
client_ordelo.schema("pgmq_public").rpc("send", {"queue_name": "owntracks", "message": {"food": "pizza"}}).execute()
```

## Advanced: Raw SQL (joins, catalog introspection, complex filters)

When you need full SQL (joins, system catalogs like `pg_trigger`, function defs, etc.), use the async pool helper:

```py
from utils_common.db_utils.sbase_pool_ops import execute_sql_query

rows = await execute_sql_query(
    "select * from pg_trigger where tgrelid = %s::regclass",
    ("delivery_summary",),
)
```

## Safety Rules for Writes

- Confirm the target environment and the exact filter keys (IDs, order_number, dispatch_id).
- For `update`/`delete`, run an equivalent `select` first and confirm the rowset size.
- Never run unfiltered `update`/`delete`; require an explicit `.eq(...)`/`.in_(...)`/tight `like(...)`.
- Prefer writing changes as small, reversible steps (and capture the “before” state in output).

## Bundled Scripts

Use the bundled examples for deterministic, repeatable operations:
- `scripts/ordelo_select.py`
- `scripts/ordelo_insert.py`
- `scripts/ordelo_update.py`
- `scripts/ordelo_delete.py`
- `scripts/ordelo_rpc.py`
