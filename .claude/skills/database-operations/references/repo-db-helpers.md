# Project DB helpers and examples

## Primary clients

- Supabase REST client: `from config import client_ordelo` (wired in `config/pg_setting.py`)
- Async Postgres pool: `await pg_settings.get_pool()` (also in `config/pg_setting.py`)

## Helpers

- Raw SQL helper: `utils_common/db_utils/sbase_pool_ops.py`
  - `execute_sql_query(query, params=None)` (async)
  - `insert_model_to_db(table_name, model_instance)` (async)
- REST wrapper helpers (httpx): `utils_common/db_utils/sbase_rest_ops.py`
  - Useful when you want a direct REST call pattern or SQL-like filter building

## Query examples

- Ad-hoc SQL snippets: `notebooks/db_queries/CommonQueries.sql`
- Supabase `.rpc(...)` example (pgmq): `notebooks/tbd_location_pub_queue.py`
