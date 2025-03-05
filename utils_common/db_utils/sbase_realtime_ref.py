# %% Imports
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from config import (
    logger,
    pg_settings,
)


# %% Define Lifespan Events
from supabase import create_async_client, AsyncClient

def handle_delivery_detail_update(payload):
    payload_dict = json.loads(payload)
    logger.success(payload_dict)




@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the pool
    pool = AsyncConnectionPool(
        conninfo=pg_settings.db_uri,
        # min_size=20,
        # max_size=200,
        # max_lifetime=0,
        # max_idle=0,
        kwargs=pg_settings.connection_kwargs,
        open=False,
    )

    pool_sync = ConnectionPool(pg_settings.db_uri)
    pool_sync.open()
    
    # Create supabase client
    supabase: AsyncClient = await create_async_client(
        pg_settings.rest_url, pg_settings.rest_key,
        # log_level="debug"
        )
    await supabase.channel("supabase_realtime").on_postgres_changes(
        "UPDATE", schema="public", table="delivery_detail", callback=handle_delivery_detail_update
    ).subscribe()

