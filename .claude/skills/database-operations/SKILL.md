---
name: database-operations
description: Query and operate on the Ordelo Supabase/Postgres database — select, insert, update, delete rows, call RPC/stored procedures, and switch between test/prod configurations. Use this skill whenever the user asks to change, query, or inspect any database table (especially rider_master, ordelo_config, restaurant_master, customer_master, delivery_summary, delivery_dispatch, or cust_rest_map), check table data, look up records by ID/order_number/rider_id/cust_id, run SQL queries, switch between test/prod environments, update admin phones, toggle rider shifts, change app URLs, or update the WABA webhook. Even if the user doesn't explicitly say "database" or "Supabase", if they mention table names, column values, rest_ref, rider_id, cust_id, config_key, prod/test mode, deployment, or WABA webhook — this skill applies. ALWAYS use this for database work, not pyrun.
---

# Database Operations

Perform reads, writes, and environment switches against the Ordelo Supabase/Postgres database
using `client_ordelo` (Supabase REST client) or direct Python Supabase client when config module fails.

## Quick Start

The simplest approach: use the config module's pre-built client:

```python
from config import client_ordelo

resp = client_ordelo.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
print(resp.data)
```

If the config module fails to load (AWS/credential errors), jump to **Fallback: Direct Supabase Client** below.

## Environment Setup

**Always run scripts with explicit Python binary and PYTHONPATH:**

```sh
REPO_ROOT=$(git rev-parse --show-toplevel)
PYTHONPATH=$REPO_ROOT python3 - <<'PY'
# your code here
PY
```

**If you get `ModuleNotFoundError` or import errors:**

Try the bootstrap installer first:
```sh
uv pip install \
  pydantic-settings boto3 loguru supabase "pywa==3.6.1" \
  "pandas==2.2.3" gspread "duckdb==1.4.3" \
  "psycopg[binary]" psycopg-pool \
  "langchain==1.2.1" "langchain-openai==1.1.7" \
  "langgraph==1.0.5" "langgraph-checkpoint-postgres==3.0.2" \
  -q
```

Then retry your script. **Do NOT use `run_setup.sh`** — it enforces `==3.13.11` which conflicts with the system's `3.13.12`.

## Fallback: Direct Supabase Client (when config module fails)

If `config` module fails due to AWS credential errors or other config issues, use direct Supabase client initialization from `env.json`:

```python
import json
from supabase import create_client

# Read env.json in repo root
with open("env.json") as f:
    env = json.load(f)

# Create client
url = env["sbase_ordelo_rest_url"]
key = env["sbase_ordelo_rest_key"]
client = create_client(url, key)

# Query normally
resp = client.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
print(resp.data)
```

This bypasses AWS Secrets Manager and uses local env.json credentials. Use this when:
- AWS credentials are not configured
- `config` module import fails  
- `pydantic_settings` validation fails
- You just need quick database access without full app initialization

## Query Patterns

### SELECT

```python
resp = (
    client.table("restaurant_master")
    .select("rest_ref, rest_name, admins, city")
    .eq("rest_ref", "SFCS")
    .execute()
)
print(resp.data)
```

### UPDATE (always filter tightly)

```python
client.table("rider_master").update(
    {"is_in_shift": True, "town": "Salisbury"}
).eq("rider_name", "Lohith").execute()
```

### INSERT

```python
client.table("food_order").insert(
    {"order_number": "ORD123", "item": "Biryani"}
).execute()
```

### UPSERT

```python
client.table("cust_rest_map").upsert(
    {"cust_id": "447000000001", "rest_ref": "ELAI", "has_consent": True},
    on_conflict="cust_id,rest_ref"
).execute()
```

### DELETE (always filter tightly)

```python
client.table("delivery_option").delete().like(
    "order_number", "WREN-TEST-%"
).execute()
```

### RPC / Stored Procedures

```python
client.rpc("dispatch_cancel_before_pickup", {"p_dispatch_id": 432}).execute()

# Schema-specific RPC
client.schema("pgmq_public").rpc(
    "send", {"queue_name": "owntracks", "message": {"key": "val"}}
).execute()
```

### Raw SQL (joins, catalog queries)

```python
from utils_common.db_utils.sbase_pool_ops import execute_sql_query

rows = await execute_sql_query(
    "select * from pg_trigger where tgrelid = %s::regclass",
    ("delivery_summary",),
)
```

## Using DataModels (preferred for lookups)

The `ordelo_datamodels` package has Pydantic models with classmethods for common lookups:

```python
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from ordelo_datamodels.delivery_pymodels import DeliverySummary, DeliveryDispatch

restaurant = RestaurantMaster.from_rest_ref("SFCS")
summary = DeliverySummary.from_order_number("ELAS-CEKT-22")
dispatch = DeliveryDispatch.from_dispatch_id(432)
```

## Safety Rules for Writes

- Confirm the target environment and exact filter keys (IDs, order_number, dispatch_id)
- For `update`/`delete`, run an equivalent `select` first and confirm rowset size
- Never run unfiltered `update`/`delete`; always use `.eq()` or `.in_()` with tight `.like()` filters
- Capture the "before" state in output so changes are reversible

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
| `delivery_option` | — | `order_number`, `vehicle_type`, `final_order_value` | — |
| `cust_rest_map` | `cust_id, rest_ref` | `has_consent`, `consent_dtts` | `CustRestMap` |
| `food_order` | `order_number` | `item`, `qty`, `price` | — |
| `thread` | `thread_id` | `rider_id`, `dispatch_id` | — |

## Switching Test/Production Environments

Use the unified deployment script to switch restaurants between test and prod safely:

```bash
source .venv/bin/activate && python notebooks/prod_deployment_checker.py --mode prod --apply
```

Handles all four steps: restaurant_master, rider_master, ordelo_config, and WABA webhook.

For manual per-table switches, reference SQL files in `.claude/skills/database-operations/references/`:
- `switch_test_prod_sfcs.sql`
- `switch_test_prod_elas.sql`
- `switch_test_prod_config.sql`

## Reference Scripts

| Script | Usage |
|---|---|
| `rider_payout.py` | Rider payout report for date range |
| `switch_elas_test_prod.py` | Switch ELAS/CHKS between test/prod |

**Run rider payout:**
```bash
PYTHONPATH=$(git rev-parse --show-toplevel) python3 \
  .claude/skills/database-operations/references/rider_payout.py \
  --start 2026-03-27
```

## Repo Pointers

- Table/function SQL definitions: `ordelo_datamodels/`
- Ad-hoc SQL examples: `notebooks/db_queries/CommonQueries.sql`
- Supabase client + async pool: `config/pg_setting.py`
- Raw SQL helpers: `utils_common/db_utils/sbase_pool_ops.py`
- REST helper wrappers: `utils_common/db_utils/sbase_rest_ops.py`
