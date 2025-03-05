# %%
from config import pg_settings
import requests 
from utils_common.thread_management import ThreadHandler

# %%
recipient = '447448440754'
# create async context
import nest_asyncio

# Apply nest_asyncio to allow running asyncio within Jupyter
nest_asyncio.apply()

async def run_async_operations():
    # Create an async pool with context manager
    from psycopg_pool import AsyncConnectionPool
    
    # Use the pool as a context manager
    async with AsyncConnectionPool(pg_settings.db_uri) as async_pool:
        # Create an async thread handler
        async_thread_handler = ThreadHandler(async_pool)
        
        # Use the async thread handler
        result = await async_thread_handler.get_active_thread(recipient)
        print(result)

# %% 
await run_async_operations()

# %%
