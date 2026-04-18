---
name: pyrun
description: Execute small Python snippets to answer ad-hoc questions, inspect live configuration/state, run database queries, or check table data. Use this skill whenever the user asks to run Python code, query the database, check table data, look up records, inspect ordelo_config values, run calculations, or verify state — even if they don't explicitly say "pyrun" or "Python". Trigger for: "run this Python", "query the database", "check if X exists in table Y", "what does the config say", "execute this script", "verify this data". This skill handles environment setup automatically, including fallback Supabase client initialization when config module fails.
---

# Pyrun

Use this skill to run short, purpose-built Python snippets in the repo to answer a specific
question, query the database, or inspect application state. Favor reusing existing imports,
utilities, and helper functions from nearby modules so the snippet stays minimal.

## Workflow

1. **Identify the minimal imports** needed for the query.
   - Prefer imports from the most relevant module that already encapsulates the logic.
   - Reuse constants, helper functions, and client instances.
   - Avoid rewriting logic inline; assemble existing pieces.

2. **Run scripts with explicit Python binary and PYTHONPATH:**
   ```sh
   PYTHONPATH=$(git rev-parse --show-toplevel) python3 - <<'PY'
   # your code here
   PY
   ```
   This bypasses venv issues and works consistently.

3. **If imports fail (ModuleNotFoundError)**, run bootstrap installer first:
   ```sh
   uv pip install \
     pydantic-settings boto3 loguru supabase "pywa==3.6.1" \
     "pandas==2.2.3" gspread "duckdb==1.4.3" \
     "psycopg[binary]" psycopg-pool \
     "langchain==1.2.1" "langchain-openai==1.1.7" \
     "langgraph==1.0.5" "langgraph-checkpoint-postgres==3.0.2" \
     -q
   ```
   Then retry. **Do NOT use `run_setup.sh`** — it enforces `==3.13.11` but the system runs `3.13.12`.

4. **If config module fails** (AWS credential errors), use direct Supabase initialization (see **Fallback** below).

5. **Keep snippets focused** — treat each pyrun like a Jupyter cell: short, focused, iterative.

---

## Standard Imports & Clients

### Database (most common)

```python
from config import client_ordelo

# SELECT
resp = client_ordelo.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
print(resp.data)
```

### DataModels (preferred for lookups)

```python
from ordelo_datamodels.delivery_pymodels import DeliverySummary, DeliveryDispatch
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

summary = DeliverySummary.from_order_number("ELAS-CEKT-22")
restaurant = RestaurantMaster.from_rest_ref("ELAI")
```

### Config & Settings

```python
from config import project_settings, waba_setting

# Check webhook
business_phone = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone.webhook_configuration)
```

### Utilities

```python
from utils_common.db_utils.sbase_pool_ops import execute_sql_query
from utils_common.waba_utils import send_wa_message
from utils_common.thread_management.thread_handler import ThreadHandler
```

---

## Fallback: Direct Supabase Client (when config module fails)

If the config module fails with AWS credential errors, initialize Supabase directly from env.json:

```python
import json
from supabase import create_client

# Load credentials from env.json (no AWS Secrets Manager needed)
with open("env.json") as f:
    env = json.load(f)

# Create client directly
url = env["sbase_ordelo_rest_url"]
key = env["sbase_ordelo_rest_key"]
client = create_client(url, key)

# Query normally
resp = client.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
for row in resp.data:
    for key, val in row.items():
        print(f"  {key}: {val}")
```

**Use this when:**
- AWS credentials not configured
- `config` module import fails
- `pydantic_settings` validation errors
- You need quick data access without full app initialization

This is a safe fallback that doesn't require AWS setup — just the local env.json.

---

## Database Query Examples

### Lookup by Order Number

```python
from config import client_ordelo

resp = client_ordelo.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
if resp.data:
    for row in resp.data:
        for key, val in row.items():
            print(f"{key}: {val}")
else:
    print("No record found")
```

### Lookup by Rider ID

```python
from config import client_ordelo

resp = client_ordelo.table("delivery_dispatch").select("*").eq("rider_id", "447000000001").limit(10).execute()
for d in resp.data:
    print(f"Dispatch {d['dispatch_id']}: {d['status']}")
```

### Check Config Values

```python
from config import client_ordelo

resp = client_ordelo.table("ordelo_config").select("*").eq("rest_ref", "ELAI").execute()
for row in resp.data:
    print(f"{row['config_key']}: {row['config_value']}")
```

### Multiple Filters

```python
from config import client_ordelo

resp = (
    client_ordelo.table("delivery_dispatch")
    .select("*")
    .eq("rider_id", "447000000001")
    .eq("status", "assigned")
    .execute()
)
print(resp.data)
```

### Insert/Update

```python
from config import client_ordelo
from datetime import datetime, timezone

client.table("delivery_dispatch").update(
    {"status": "completed", "status_update_dtts": datetime.now(timezone.utc).isoformat()}
).eq("dispatch_id", 432).execute()
```

### Call Stored Procedure (RPC)

```python
from config import client_ordelo

response = client_ordelo.rpc("dispatch_complete_func", {"p_dispatch_id": 432}).execute()
print(response.data)
```

---

## Tables Reference

| Table | Primary Key | Key Columns | DataModel |
|---|---|---|---|
| `delivery_summary` | `order_number` | `rest_ref`, `customer_id`, `status`, `pickup_time` | `DeliverySummary` |
| `delivery_detail` | `order_number` | `rest_id`, `customer_id`, `rider_id`, `dispatch_id`, `status` | `DeliveryDetail` |
| `delivery_dispatch` | `dispatch_id` | `order_number`, `rider_id`, `status`, `vehicle_type` | `DeliveryDispatch` |
| `delivery_option` | — | `order_number`, `vehicle_type`, `final_order_value` | — |
| `restaurant_master` | `rest_ref` | `rest_id`, `rest_name`, `admins`, `lat`, `lon`, `city` | `RestaurantMaster` |
| `customer_master` | `cust_id` | `cust_name`, `house_number`, `street_name`, `city` | `CustomerMaster` |
| `rider_master` | `rider_id` | `rider_name`, `vehicle_type`, `is_in_shift`, `town` | — |
| `ordelo_config` | `config_key` | `config_value`, `rest_ref` | — |
| `cust_rest_map` | `cust_id, rest_ref` | `has_consent`, `consent_dtts` | `CustRestMap` |
| `thread` | `thread_id` | `rider_id`, `dispatch_id` | — |

---

## General Examples

### Check Webhook Config

```python
from config import waba_setting

business_phone = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone.webhook_configuration)
```

### List Active Dispatches

```python
from config import client_ordelo

resp = (
    client_ordelo.table("delivery_dispatch")
    .select("dispatch_id, order_number, rider_id, status")
    .eq("status", "assigned")
    .execute()
)
for d in resp.data:
    print(d)
```

### Inspect Project Settings

```python
from config import project_settings

print(f"REST Ref: {project_settings.rest_ref}")
print(f"Project Root: {project_settings.project_root}")
```

### Debug Thread Messages

```python
from utils_common.thread_management.thread_handler import ThreadHandler

handler = ThreadHandler(thread_id="some_thread_id")
messages = handler.debug_thread()
for msg in messages:
    print(msg.get('content', ''))
```

---

## Environment Notes

- **Python version**: `pyproject.toml` requires `==3.13.11` but the system runs `3.13.12`.
  `uv sync` will fail — use `uv pip install` directly instead, as shown above.

- **Stale `.venv`**: The existing `.venv` contains Python 3.11. Always use absolute path `/usr/bin/python3` to avoid this.

- **Don't run `run_setup.sh` via source** — it uses `set -euo pipefail` which silently fails mid-script
  when `uv sync` exits. Always run bootstrap `uv pip install` manually instead.

---

## Iterative Development

Treat each pyrun call like a Jupyter cell:
1. Run a small query to verify connectivity
2. Expand the query based on what you learn
3. Print intermediate results to debug
4. Refine as needed

Don't try to write complex multi-function scripts in one shot — iterate.
