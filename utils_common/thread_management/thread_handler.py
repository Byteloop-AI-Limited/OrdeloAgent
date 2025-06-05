"""Provides ThreadHandler for asynchronous thread operations in Postgres
    . Utilizes psycopg3 for async database access
    . Defines create_thread and get_active_thread methods
"""

import uuid
import psycopg

class ThreadHandler:
    def __init__(self, pool):
        self.pool = pool

    async def create_thread(self, from_number):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    thread_id = str(uuid.uuid4())
                    is_active = True
                    await cur.execute(
                        """
                        INSERT INTO thread (thread_id, from_number, is_active)
                        VALUES (%s, %s, %s)
                        """,
                        (thread_id, from_number, is_active),
                    )
                    return {
                        "thread_id": thread_id,
                        "from_number": from_number,
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
                        ORDER BY dtts DESC
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
