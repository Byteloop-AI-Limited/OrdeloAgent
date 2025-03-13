"""
Utility functions for postgres with psycopg3
"""
# %%

import uuid
from datetime import datetime
import psycopg

# conninfo = pg_settings.db_uri


class ThreadHandler:
    def __init__(self, pool):
        self.pool = pool

    async def create_thread(self, from_number):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    thread_id = str(uuid.uuid4())
                    thread_ts = datetime.now().isoformat()
                    is_active = True
                    await cur.execute(
                        """
                        INSERT INTO thread (
                            thread_id, 
                            from_number, 
                            thread_ts, 
                            is_active
                            )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (thread_id, from_number, thread_ts, is_active),
                    )
                    return {
                        "thread_id": thread_id,
                        "from_number": from_number,
                        "thread_ts": thread_ts,
                        "is_active": is_active,
                    }
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in create_thread: {e}")
            raise

    async def get_active_thread(self, from_number):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM thread
                        WHERE from_number = %s AND is_active = TRUE
                        ORDER BY thread_ts DESC
                        LIMIT 1
                        """,
                        (from_number,),
                    )
                    result = await cur.fetchone()
                    return result
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in get_active_thread: {e}")
            raise

    async def make_threads_inactive(self, from_number):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        UPDATE thread
                        SET is_active = FALSE
                        WHERE from_number = %s
                    """,
                        (from_number,),
                    )
                    affected_rows = cur.rowcount
            return {"message": f"{affected_rows} thread(s) marked as inactive."}
        except psycopg.Error as e:
            print(f"Error in make_threads_inactive: {e}")
            raise

    async def get_or_create_thread(self, from_number):
        # Try to get an active thread
        active_thread = await self.get_active_thread(from_number)
        if active_thread:
            # Active thread exists, return its ID
            return active_thread["thread_id"], False
        else:
            # No active thread, create a new one
            new_thread = await self.create_thread(from_number)
            return new_thread["thread_id"], True

# %% thread usage
# thread_handler = ThreadHandler(pool)
# thread_id, is_new_thread_created = await thread_handler.get_or_create_thread(recipient)

# %% graph checkpointer usage
"""
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async with AsyncConnectionPool(
    conninfo=pg_settings.db_uri,
    max_size=20,
    kwargs=pg_settings.connection_kwargs,
) as pool:
    checkpointer = AsyncPostgresSaver(pool)
    
    # getting checkpoint
    checkpoint = await checkpointer.aget(
        {"configurable": {"thread_id": "1"}}
    )

    # graph checkpointer
    graph = workflow.compile(checkpointer=checkpointer)
    # _state = await graph.aget_state(config)

"""