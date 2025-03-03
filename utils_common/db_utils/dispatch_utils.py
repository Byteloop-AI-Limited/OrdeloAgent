"""
Utility functions for dispatch operations in the database.
"""
from psycopg_pool import AsyncConnectionPool, ConnectionPool
import json

async def call_dispatch_complete(pool: AsyncConnectionPool, dispatch_id: int) -> dict:
    """
    Call the dispatch_complete_func PostgreSQL function and return the result as a Python dictionary.
    
    Args:
        pool: Database connection pool
        dispatch_id: The ID of the dispatch to complete
        
    Returns:
        dict: A dictionary containing the dispatch details with column names as keys
    """
    query = "SELECT dispatch_complete_func(%s);"
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, (dispatch_id,))
            result = await cur.fetchone()
            
            if result and result[0]:
                # Result is already a JSON object from PostgreSQL
                return result[0]
            
            return {}

def call_dispatch_complete_sync(pool: ConnectionPool, dispatch_id: int) -> dict:
    """
    Synchronous version to call the dispatch_complete_func PostgreSQL function 
    and return the result as a Python dictionary.
    
    Args:
        pool: Database connection pool
        dispatch_id: The ID of the dispatch to complete
        
    Returns:
        dict: A dictionary containing the dispatch details with column names as keys
    """
    query = "SELECT dispatch_complete_func(%s);"
    
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (dispatch_id,))
            result = cur.fetchone()
            
            if result and result[0]:
                # Result is already a JSON object from PostgreSQL
                return result[0]
            
            return {}
