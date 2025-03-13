"""
Application state initialization module.
This module provides functions to initialize and manage application state resources.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from ordelo.agents.rider_agent import builder
from psycopg_pool import AsyncConnectionPool, ConnectionPool

from config import (
    pg_settings,
)
from utils_common.thread_management import ThreadHandler

# Global variables to store initialized resources
pool = None
pool_sync = None
checkpointer = None
thread_handler = None
graph = None
client = None

async def init_app_state():
    """
    Initialize application state resources.
    This function must be called within an async context.
    
    Returns:
        tuple: A tuple containing (pool, pool_sync, checkpointer, thread_handler, graph, client)
    """
    global pool, pool_sync, checkpointer, thread_handler, graph, client
    
    # Initialize the pool if not already initialized
    if pool is None:
        pool = AsyncConnectionPool(
            conninfo=pg_settings.db_uri,
            kwargs=pg_settings.connection_kwargs,
            open=False,
            min_size=2,
            max_size=10,
            timeout=10,  # Connection timeout in seconds
            max_idle=300,  # Maximum idle time for connections in seconds
            reconnect_timeout=3,  # Time to wait between reconnection attempts
        )
        # Explicitly open the pool
        await pool.open()
    
    # Initialize pool_sync if not already initialized
    if pool_sync is None:
        pool_sync = ConnectionPool(pg_settings.db_uri)
        pool_sync.open()
    
    # Initialize other resources if not already initialized
    if checkpointer is None:
        checkpointer = AsyncPostgresSaver(pool)
    
    if thread_handler is None:
        thread_handler = ThreadHandler(pool)
    
    if graph is None:
        graph = builder.compile(checkpointer=MemorySaver())
    
    if client is None:
        client = pg_settings.client
    
    return pool, pool_sync, checkpointer, thread_handler, graph, client

def get_app_state():
    """
    Get the current application state resources.
    This function can be called from a synchronous context.
    
    Returns:
        tuple: A tuple containing (pool, pool_sync, checkpointer, thread_handler, graph, client)
        Note: Returns None for resources that haven't been initialized yet.
    """
    return pool, pool_sync, checkpointer, thread_handler, graph, client