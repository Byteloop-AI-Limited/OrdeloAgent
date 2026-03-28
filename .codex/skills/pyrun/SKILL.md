---
name: pyrun
description: Execute small Python snippets in this repo to answer ad-hoc questions, inspect live configuration/state, or run database queries against Supabase/Postgres. Use when the user asks to run Python code, query the DB, check table data, look up records, or inspect ordelo_config values — even if they don't explicitly say "pyrun".
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: |
            cd /home/basal/bloop/OrdeloAgent && \
            if [ ! -f .venv/bin/activate ]; then
              source run_setup.sh
            else
              source .venv/bin/activate
            fi
---

# Pyrun

Use this skill to run short, purpose-built Python snippets in the repo to answer a specific
question or query the database. Favor reusing existing imports, utilities, and helper functions
from nearby modules so the snippet stays as small as possible.

## Workflow

1) Identify the minimal imports and objects needed for the query.
   - Prefer imports from the most relevant module(s) that already encapsulate the logic.
   - Reuse constants, helper functions, and client instances from the referenced file(s).
   - Avoid rewriting logic inline; assemble existing pieces instead.

2) The venv is activated automatically via the PreToolUse hook — no manual `source` needed.
   If the hook fails or imports break, run setup manually:
   ```sh
   source run_setup.sh
   ```

3) Write a tiny script using a `python - <<'PY'` heredoc; run from the repo root.
   - Treat each pyrun like a Jupyter cell: keep it focused, short, and iterative.
   - If follow-up questions are likely, keep the snippet modular and reuse imports.

4) If the code needs network (e.g., AWS Secrets Manager, Supabase, external APIs), ensure
   the sandbox allows it.

5) Print only the required fields; avoid dumping secrets.

---

## Database Queries

One of pyrun's core capabilities is querying the Ordelo Supabase/Postgres database using
the `client_ordelo` connection object. This is a synchronous Supabase `Client` from the
`supabase` Python library.

### Import

```python
from config import client_ordelo
```

### Query Patterns

**SELECT** — fetch rows with filters:
```python
from config import client_ordelo

resp = (
    client_ordelo.table("delivery_summary")
    .select("*")
    .eq("order_number", "ORD123")
    .limit(1)
    .execute()
)
print(resp.data)
```

**SELECT with multiple filters:**
```python
resp = (
    client_ordelo.table("delivery_dispatch")
    .select("*")
    .eq("rider_id", "447000000001")
    .eq("status", "assigned")
    .execute()
)
print(resp.data)
```

**UPDATE:**
```python
from config import client_ordelo
from datetime import datetime, timezone

client_ordelo.table("delivery_dispatch").update(
    {"status": "pickedup", "status_update_dtts": datetime.now(timezone.utc).isoformat()}
).eq("dispatch_id", 432).execute()
```

**INSERT:**
```python
client_ordelo.table("food_order").insert({"order_number": "ORD123", "item": "Biryani"}).execute()
```

**UPSERT** (insert or update on conflict):
```python
client_ordelo.table("cust_rest_map").upsert(
    {"cust_id": "447000000001", "rest_ref": "ELAI", "has_consent": True},
    on_conflict="cust_id,rest_ref"
).execute()
```

**RPC** — call a stored procedure / database function:
```python
response = client_ordelo.rpc(
    "dispatch_complete_func", {"p_dispatch_id": 432}
).execute()
print(response.data)
```

**Schema-specific RPC:**
```python
client_ordelo.schema("pgmq_public").rpc(
    "send", {"queue_name": "owntracks", "message": {"key": "val"}}
).execute()
```

### Extracting Data (defensive pattern used across codebase)

```python
data = (
    resp["data"] if isinstance(resp, dict) and "data" in resp
    else resp.data if hasattr(resp, "data")
    else None
)
```

### Using DataModels (preferred for lookups)

The `ordelo_datamodels` package has Pydantic models with built-in classmethods that handle
the query + validation for you. Prefer these over raw `client_ordelo` calls when a classmethod
exists for what you need.

```python
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliverySummary, DeliveryDispatch
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from ordelo_datamodels.customer_master_pymodel import CustomerMaster
from ordelo_datamodels.cust_rest_map_pymodel import CustRestMap

# Lookup by primary key
detail = DeliveryDetail.from_order_number("ORD123")
summary = DeliverySummary.from_order_number("ORD123")
dispatch = DeliveryDispatch.from_dispatch_id(432)
restaurant = RestaurantMaster.from_rest_ref("ELAI")
customer = CustomerMaster.from_cust_id("447000000001")

# Upsert
CustomerMaster.upsert(cust_id="447000000001", cust_name="Lohith", city="London")
```

---

## Tables Reference

| Table | Primary Key | Key Columns | DataModel |
|---|---|---|---|
| `delivery_summary` | `order_number` | `rest_ref`, `customer_id`, `status`, `rest_confirmation_code`, `cust_confirmation_code`, `pickup_time`, `dt` | `DeliverySummary` |
| `delivery_detail` | `order_number` | `rest_id`, `customer_id`, `rider_id`, `dispatch_id`, `status`, `distance`, `rider_payout` | `DeliveryDetail` |
| `delivery_dispatch` | `dispatch_id` | `order_number`, `rider_id`, `status`, `vehicle_type`, `distance`, `status_update_dtts` | `DeliveryDispatch` |
| `restaurant_master` | `rest_ref` | `rest_id`, `rest_name`, `admins`, `lat`, `lon`, `city`, `postcode` | `RestaurantMaster` |
| `customer_master` | `cust_id` | `cust_name`, `house_number`, `street_name`, `city`, `postcode`, `lat`, `lon` | `CustomerMaster` |
| `cust_rest_map` | `cust_id, rest_ref` | `has_consent`, `consent_dtts` | `CustRestMap` |
| `rider_master` | `rider_id` | `rider_name`, `vehicle_type`, `status` | — |
| `food_order` | `order_number` | `item`, `qty`, `price` | — |
| `order_item` | — | `order_number`, `item_name`, `qty` | — |
| `ordelo_config` | `config_key` | `config_value`, `rest_ref` | — |
| `thread` | `thread_id` | `rider_id`, `dispatch_id` | — |
| `delivery_inflight` | — | `dispatch_id`, `status` | — |
| `takeaway_summary` | — | `order_number`, `rest_ref`, `status` | — |
| `waba_es` | — | WABA embedded signup records | — |
| `delivery_option` | — | delivery configuration options | — |

---

## General Examples

**Check webhook config:**
```python
from config import waba_setting
business_phone_number = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone_number.webhook_configuration)
```

**Read ordelo_config for a restaurant:**
```python
from config import client_ordelo
resp = client_ordelo.table("ordelo_config").select("*").eq("rest_ref", "ELAI").execute()
for row in resp.data:
    print(f"{row['config_key']}: {row['config_value']}")
```

**List all active dispatches:**
```python
from config import client_ordelo
resp = client_ordelo.table("delivery_dispatch").select("dispatch_id, order_number, rider_id, status").eq("status", "assigned").execute()
for d in resp.data:
    print(d)
```

## Reference scripts

- `scripts/debug_thread_messages.py` prints only the message content for a given thread_id using `debug_thread`.
