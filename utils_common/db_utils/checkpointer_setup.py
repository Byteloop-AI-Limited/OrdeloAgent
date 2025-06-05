# %%
"""
One-off script to initialise LangGraph Postgres checkpoint table.
    . Opens connection pool using project `pg_settings`
    . Creates `PostgresSaver` and calls `.setup()` which issues DDL
    . Run manually to prepare database for graph checkpointing
"""
from psycopg_pool import ConnectionPool
from config import pg_settings
from langgraph.checkpoint.postgres import PostgresSaver

# %%
with ConnectionPool(
    # Example configuration
    conninfo=pg_settings.db_uri,
    min_size=1,
    max_size=20,
    kwargs={**pg_settings.connection_kwargs, "autocommit": True},
) as pool:
    checkpointer = PostgresSaver(pool)

    # NOTE: you need to call .setup() the first time you're using your checkpointer
    checkpointer.setup()