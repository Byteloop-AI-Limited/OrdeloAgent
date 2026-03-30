---
name: database-operations
description: Query and operate on the Ordelo Supabase/Postgres database — select, insert, update, delete rows, call RPC/stored procedures, and switch between test/prod configurations. Use this skill whenever the user asks to change, query, or inspect any database table — especially rider_master, ordelo_config, restaurant_master, customer_master, delivery_summary, delivery_dispatch, or cust_rest_map. Also use when switching test/prod environments, updating admin phone numbers, toggling rider shifts, or changing app URLs in ordelo_config. Even if the user doesn't say "database", if they mention table names, column values, rest_ref, rider_id, cust_id, or config_key — this skill applies.
---

# Database Operations

Perform reads, writes, and environment switches against the Ordelo Supabase/Postgres database
using `client_ordelo` (Supabase REST client) or raw SQL via the async pool.

## Environment Setup

The project's `.venv` is stale (Python 3.11) and `run_setup.sh` silently fails on `uv sync`
due to a Python version mismatch (`pyproject.toml` requires 3.13.11, machine has 3.13.12).
Never rely on venv activation or `source run_setup.sh` for database scripts.

**Always run scripts with the explicit Python binary and PYTHONPATH:**

```sh
PYTHONPATH=/home/basal/bloop/OrdeloAgent .venv/bin/python3.13 - <<'PY'
# your code here
PY
```

**If imports fail (ModuleNotFoundError)**, bootstrap deps first, then retry:

```sh
uv pip install \
  pydantic-settings boto3 loguru supabase "pywa==3.6.1" \
  "pandas==2.2.3" gspread "duckdb==1.4.3" \
  "psycopg[binary]" psycopg-pool \
  "langchain==1.2.1" "langchain-openai==1.1.7" \
  "langgraph==1.0.5" "langgraph-checkpoint-postgres==3.0.2" \
  --python .venv/bin/python3.13 -q
```

## Quick Start

```python
from config import client_ordelo
```

This is the synchronous Supabase `Client` wired in `config/pg_setting.py`. All examples below
use this import.

### SELECT

```python
resp = (
    client_ordelo.table("restaurant_master")
    .select("rest_ref, rest_name, admins, city")
    .eq("rest_ref", "SFCS")
    .execute()
)
print(resp.data)
```

### UPDATE

```python
client_ordelo.table("rider_master").update(
    {"is_in_shift": True, "town": "Salisbury", "vehicle_type": "bicycle"}
).eq("rider_name", "Lohith").execute()
```

### INSERT

```python
client_ordelo.table("food_order").insert(
    {"order_number": "ORD123", "item": "Biryani"}
).execute()
```

### UPSERT

```python
client_ordelo.table("cust_rest_map").upsert(
    {"cust_id": "447000000001", "rest_ref": "ELAI", "has_consent": True},
    on_conflict="cust_id,rest_ref"
).execute()
```

### DELETE (always filter tightly)

```python
client_ordelo.table("delivery_option").delete().like(
    "order_number", "WREN-TEST-%"
).execute()
```

### RPC / Stored Procedures

```python
client_ordelo.rpc("dispatch_cancel_before_pickup", {"p_dispatch_id": 432}).execute()

# Schema-specific RPC
client_ordelo.schema("pgmq_public").rpc(
    "send", {"queue_name": "owntracks", "message": {"key": "val"}}
).execute()
```

### Raw SQL (joins, catalog introspection)

When you need full SQL (joins, system catalogs like `pg_trigger`, function defs):

```python
from utils_common.db_utils.sbase_pool_ops import execute_sql_query

rows = await execute_sql_query(
    "select * from pg_trigger where tgrelid = %s::regclass",
    ("delivery_summary",),
)
```

## Using DataModels (preferred for lookups)

The `ordelo_datamodels` package has Pydantic models with classmethods that handle
query + validation. Prefer these over raw `client_ordelo` calls when a classmethod exists.

```python
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from ordelo_datamodels.customer_master_pymodel import CustomerMaster
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliverySummary, DeliveryDispatch
from ordelo_datamodels.cust_rest_map_pymodel import CustRestMap

restaurant = RestaurantMaster.from_rest_ref("SFCS")
customer = CustomerMaster.from_cust_id("447000000001")
dispatch = DeliveryDispatch.from_dispatch_id(432)
```

## Safety Rules for Writes

- Confirm the target environment and exact filter keys (IDs, order_number, dispatch_id).
- For `update`/`delete`, run an equivalent `select` first and confirm the rowset size.
- Never run unfiltered `update`/`delete`; always use `.eq()`/`.in_()`/tight `.like()`.
- Capture the "before" state in output so changes are reversible.

## Tables Reference

| Table | Primary Key | Key Columns | DataModel |
|---|---|---|---|
| `restaurant_master` | `rest_ref` | `rest_id`, `rest_name`, `admins`, `lat`, `lon`, `city`, `postcode` | `RestaurantMaster` |
| `rider_master` | `rider_id` | `rider_name`, `vehicle_type`, `is_in_shift`, `town` | — |
| `customer_master` | `cust_id` | `cust_name`, `house_number`, `street_name`, `city`, `postcode`, `lat`, `lon` | `CustomerMaster` |
| `ordelo_config` | `config_key` | `config_value`, `rest_ref` | — |
| `delivery_summary` | `order_number` | `rest_ref`, `customer_id`, `status`, `pickup_time`, `dt` | `DeliverySummary` |
| `delivery_detail` | `order_number` | `rest_id`, `customer_id`, `rider_id`, `dispatch_id`, `status` | `DeliveryDetail` |
| `delivery_dispatch` | `dispatch_id` | `order_number`, `rider_id`, `status`, `vehicle_type` | `DeliveryDispatch` |
| `cust_rest_map` | `cust_id, rest_ref` | `has_consent`, `consent_dtts` | `CustRestMap` |
| `food_order` | `order_number` | `item`, `qty`, `price` | — |
| `thread` | `thread_id` | `rider_id`, `dispatch_id` | — |

## Switching Test / Production Environments

Reference SQL files are provided for switching specific restaurants between test and prod.
Read the relevant file from `.codex/skills/database-operations/references/` before executing:

| File | What it switches |
|---|---|
| `switch_test_prod_sfcs.sql` | SFCS restaurant_master + rider_master only |
| `switch_test_prod_elas.sql` | ELAS/CHKS restaurant_master + rider_master only |
| `switch_test_prod_config.sql` | Global ordelo_config URLs (ORDELO_APP_URL, ELAS_APP_URL, SFCS_APP_URL, etc.) |

**Important:** Restaurant-specific switches (SFCS, ELAS) only update `restaurant_master` and
`rider_master`. They do NOT touch `ordelo_config` or app URLs. To switch config URLs, use
`switch_test_prod_config.sql` separately.

Each file has three sections: **Verification Queries** (run first to check current state),
**Test Setup** (switch to test), and **Production Setup** (switch to prod). Always run the
verification queries before applying changes so you can confirm current state and revert if needed.

**Example — switch SFCS to test mode:**

```sh
PYTHONPATH=/home/basal/bloop/OrdeloAgent .venv/bin/python3.13 - <<'PY'
from config import client_ordelo

# Verify current state first
resp = client_ordelo.table("restaurant_master").select("rest_ref, admins, city").eq("rest_ref", "SFCS").execute()
print("BEFORE:", resp.data)

# Apply test config (restaurant_master + rider_master only, NOT ordelo_config)
client_ordelo.table("restaurant_master").update(
    {"admins": ["447919202938"], "rest_stale_active_threads_minutes": 10,
     "restaurant_start_time": 11, "restaurant_end_time": 21.30, "city": "dummy"}
).eq("rest_ref", "SFCS").execute()

client_ordelo.table("rider_master").update(
    {"is_in_shift": True, "town": "dummy", "vehicle_type": "bicycle"}
).eq("rider_name", "Lohith").execute()

print("Switched SFCS to TEST mode")
PY
```

## Reference Scripts

Python scripts in `.codex/skills/database-operations/references/` for common reporting tasks:

| Script | Usage |
|---|---|
| `rider_payout.py` | Rider payout report for a date range — detailed per-order and aggregated totals. Joins `delivery_dispatch` → `rider_master` → `rider_registrations` → `delivery_option`. Excludes internal test rider (Lohith). |

**Run rider payout report:**
```sh
PYTHONPATH=/home/user/OrdeloAgent /usr/bin/python3.13 \
  .codex/skills/database-operations/references/rider_payout.py \
  --start 2026-03-27 --end 2026-04-03
```

## Repo Pointers (load as needed)

- Table/function SQL definitions: `ordelo_datamodels/` — see `references/ordelo-datamodels.md`
- Ad-hoc SQL examples: `notebooks/db_queries/CommonQueries.sql`
- Supabase client + async pool: `config/pg_setting.py`
- Raw SQL helpers: `utils_common/db_utils/sbase_pool_ops.py`
- REST helper wrappers: `utils_common/db_utils/sbase_rest_ops.py`

## Bundled Scripts

Deterministic CLI scripts in `.codex/skills/database-operations/scripts/`:

| Script | Usage |
|---|---|
| `ordelo_select.py` | `--table T --eq col=val --select "col1,col2" --limit 10` |
| `ordelo_update.py` | `--table T --eq col=val --set-json '{"col":"newval"}'` |
| `ordelo_insert.py` | `--table T --json '{"col":"val"}'` |
| `ordelo_delete.py` | `--table T --eq col=val --confirm` |
| `ordelo_rpc.py` | `--function fn_name --json '{"param":"val"}'` |

Run them with:
```sh
PYTHONPATH=/home/basal/bloop/OrdeloAgent .venv/bin/python3.13 \
  .codex/skills/database-operations/scripts/ordelo_select.py \
  --table restaurant_master --eq rest_ref=SFCS
```
