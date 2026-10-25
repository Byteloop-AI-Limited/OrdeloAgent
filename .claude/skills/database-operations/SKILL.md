---
name: database-operations
description: Query and operate on the Ordelo Supabase/Postgres database — select, insert, update, delete rows, call RPC/stored procedures, and switch between test/prod configurations. Use this skill whenever the user asks to change, query, or inspect any database table (especially rider_master, ordelo_config, restaurant_master, customer_master, delivery_summary, delivery_dispatch, or cust_rest_map), check table data, look up records by ID/order_number/rider_id/cust_id, run SQL queries, switch between test/prod environments, update admin phones, toggle rider shifts, change app URLs, update the WABA webhook, or create/list/revoke Telegram invites (t_invites). Even if the user doesn't explicitly say "database" or "Supabase", if they mention table names, column values, rest_ref, rider_id, cust_id, config_key, prod/test mode, deployment, WABA webhook, or Telegram invite links — this skill applies. ALWAYS use this for database work, not pyrun. Use the anon client first and the service-role key only after a permission error. NEVER run a delete without explicit user approval.
---

# Database Operations

Perform reads, writes, and environment switches against the Ordelo Supabase/Postgres database
using `client_ordelo` (Supabase REST client, anon key) or a direct Python Supabase client when the config module fails.

> ## 🛑 NEVER RUN A DELETE WITHOUT EXPLICIT APPROVAL 🛑
> **Do not run any `DELETE` / `.delete()` / `TRUNCATE` / `DROP` / `ordelo_delete.py` statement, on any table, in any
> environment, unless the user has approved THAT exact delete in this conversation.**
> - Approval for an insert, update, revoke or switch is **not** approval to delete. A task that "needs" a delete
>   (cleanup, retry, test data, "start fresh") is not approval either. Ask first.
> - Before asking: run the equivalent `select`, show the user the rows and the count that would be deleted.
> - Then wait for a clear yes. Do not infer approval from silence, from earlier messages, or from your own plan.
> - `scripts/ordelo_delete.py` refuses to run without `--approved-by` and `--confirm`. Never fill `--approved-by`
>   with anything the user did not actually say. Never bypass the script with raw SQL or another client.
> - Prefer reversible alternatives (status flags such as `revoked`, soft-delete) and offer them in the same message.

## Which client to use (anon first, service role only on error)

1. **Start with `client_ordelo`** (anon key) for every query.
2. **Switch to `client_ordelo_service`** (`from config import client_ordelo_service`, service-role key, bypasses RLS)
   only when the anon query **returns an error**: Postgres `42501` (permission denied / row-level security
   violation) or PostgREST `PGRST301`/`PGRST302`. Say in your reply that you fell back and why.
3. **RLS can also hide rows silently**: a select can return `[]` instead of an error. If an empty result is
   unexpected, repeat the same read with the service role before concluding the data is missing.
   `t_invites`, `t_invites_shareable` and the `tgram_*` functions are service-role only, so use
   `client_ordelo_service` for those straight away.
4. Writes with the service role bypass RLS entirely: keep filters tight and follow the write rules below.

The helper scripts in `scripts/` do steps 1-2 automatically (anon first, retry with service on a permission
error) and take `--service` to skip the anon attempt (step 3). In the examples below, `client` means whichever
client the rules above select.

## Setup Priority (follow in order)

### Step 1 — Full venv via run_setup.sh (preferred)

`run_setup.sh` creates `.venv`, syncs all deps, and validates AWS credentials in one shot.
`pyproject.toml` requires `>=3.11`, so it works with whatever Python is on the system:

```sh
./run_setup.sh               # creates .venv, runs uv sync, validates AWS vars
source .venv/bin/activate
```

After activation, all imports work normally:

```sh
REPO_ROOT=$(git rev-parse --show-toplevel)
PYTHONPATH=$REPO_ROOT python3 - <<'PY'
from config.pg_setting import client_ordelo as client  # anon first; see 'Which client to use'
resp = client.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
print(resp.data)
PY
```

### Step 2 — Lightweight bootstrap (no venv, quicker for one-off queries)

Use when you need a fast one-off query without installing Python 3.13.11.
Installs packages into system Python, then loads secrets from AWS Secrets Manager:

```sh
uv pip install \
  pydantic-settings boto3 loguru supabase "pywa==3.6.1" \
  "pandas==2.2.3" gspread "duckdb==1.4.3" \
  "psycopg[binary]" psycopg-pool \
  "langchain==1.2.1" "langchain-openai==1.1.7" \
  "langgraph==1.0.5" "langgraph-checkpoint-postgres==3.0.2" \
  -q
```

Then query using the AWS-backed config:

```sh
PYTHONPATH=$(git rev-parse --show-toplevel) python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from aws_setting import ordelo_agent_env          # fetches secrets from AWS Secrets Manager
from supabase import create_client
client = create_client(ordelo_agent_env["sbase_ordelo_rest_url"], ordelo_agent_env["sbase_ordelo_rest_key"])  # anon key; use sbase_ordelo_service_key only after a permission error
resp = client.table("delivery_summary").select("*").eq("order_number", "ELAS-CEKT-22").execute()
print(resp.data)
PY
```

> **Note:** `env.json` does not exist locally — credentials always come from AWS Secrets Manager
> via `aws_setting.ordelo_agent_env`. Never attempt to open `env.json`.

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

### DELETE (⚠️ REQUIRES EXPLICIT USER APPROVAL FIRST, see the warning at the top)

Do not run this without the user approving this exact delete. Always filter tightly.

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
- **Never run any `delete` without the user's explicit approval of that exact delete** (see the warning at the top)
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
| `t_invites` | `invite_code` | `rest_ref`, `phone_number`, `status`, `expires_at`, `telegram_user_id`, `telegram_chat_id` (see Telegram Invites) | — |
| `t_invites_shareable` (view) | `invite_code` | everything in `t_invites` plus `invite_link` | — |
| `delivery_summary` / `takeaway_summary` decisions | — | Accept/Decline/pickup go through the RPCs `restaurant_order_decide` / `restaurant_order_set_pickup` (service role; Telegram taps reach them through `t_order_decide` / `t_order_set_pickup`, which check the tapper is a linked admin); do not hand-edit `restaurant_confirmation_status`. `delivery_summary.status` may now be `declined` | — |
| `t_inbox` | `bot_key, update_id` | `kind`, `tuid`, `status` (`processing`/`done`/`failed`), `error`, `received_at` — Telegram updates handled; service-role only; purged by `t_housekeeping()` (`ordelo_datamodels/telegram/t_housekeeping.sql`; not scheduled on live, see docs/to-do.md) | — |
| `t_order_alerts` | `id` | `bot_key, order_number, order_type, rest_ref, offset_secs, n, of_n, due_at, status` (`pending`/`sent`/`superseded`/`cancelled`) — Telegram order-alert schedule written by `job_t_order_alerts()`; service-role only | — |
| `t_sent_messages` | `id` (unique `bot_key, tcid, message_id`) | `tcid`, `tuid` (NULL = group), `subject_ref`, `order_type`, `card_status`, `state` (`live`/`taken`/`closed`), `taken_for`, `close_reason` — where each Telegram order-card copy lives; cleanup only; service-role only | — |

## Telegram Invites (`t_invites`)

Day-to-day SOP for onboarding restaurant admins onto the Telegram restaurant-admin bot. Prerequisite: the
migration `ordelo_datamodels/telegram/t_invites.sql` has been run and
`ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME` is set (otherwise `invite_link` comes back NULL). The migration
file's header explains how the table, view and functions fit together.

```sql
-- Create an invite (code and 48h expiry are generated):
--   INSERT INTO t_invites (rest_ref, phone_number) VALUES ('ELAS', '+44 7700 900123')
--   RETURNING invite_code;
-- Get the link to send privately:
--   SELECT invite_code, rest_ref, phone_number, status, invite_link FROM t_invites_shareable
--   WHERE status = 'pending' ORDER BY created_at DESC;
-- See who claimed what (check the Telegram name is the person you expected):
--   SELECT rest_ref, phone_number, telegram_username, telegram_first_name, telegram_user_id, claimed_at
--   FROM t_invites WHERE status = 'claimed';
-- Revoke (works on pending AND claimed invites; takes effect on the person's next action):
--   UPDATE t_invites SET status = 'revoked' WHERE invite_code = '<code>';
```

Same operations through the service-role client (`from config import client_ordelo_service`; these objects are service-role only, so no anon attempt):

```python
client_ordelo_service.table("t_invites").insert({"rest_ref": "ELAS", "phone_number": "+44 7700 900123"}).execute()  # data[0]["invite_code"]
client_ordelo_service.table("t_invites_shareable").select("invite_code,rest_ref,phone_number,status,invite_link") \
    .eq("status", "pending").order("created_at", desc=True).execute()
client_ordelo_service.table("t_invites").select("rest_ref,phone_number,telegram_username,telegram_first_name,telegram_user_id,claimed_at") \
    .eq("status", "claimed").execute()
client_ordelo_service.table("t_invites").update({"status": "revoked"}).eq("invite_code", "<code>").execute()
```

Rules for agents:
- Invite links are secrets: deliver each one only to the intended person over a private channel, never in a shared
  chat, log, ticket or commit.
- Only the operator-supplied `rest_ref` and `phone_number` go into an insert; never set `status`, `invite_code`,
  `telegram_*` or `phone_verified` by hand (the bot fills those in when the person confirms).
- Before a revoke, `select` the row by `invite_code` and confirm the restaurant and the claimer's Telegram name
  with the operator. Revoking a claimed invite cuts that person off; there is no un-revoke, so issue a new invite.
- **Never delete rows without the user's explicit approval** (see the warning at the top): claimed rows are the
  audit trail of who was onboarded where. Revoke instead.

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

## Admin roster (replaces Telegram invites for restaurant admins)

Source of truth for membership is `restaurant_master.admins`. Link state and channels live in `restaurant_admin` (view `admin_roster`). Inspect with `SELECT * FROM admin_roster WHERE rest_ref = 'STRK'`; change channels with `admin_set_channels(...)`, remove a Telegram link with `admin_unlink_telegram(...)` (or the sys-admin page). Do not create new `t_invites` for admins; existing claimed invites keep working until P3. Never apply `ordelo_datamodels/migrations/admin_roster_p1.sql` without the owner's approval.
