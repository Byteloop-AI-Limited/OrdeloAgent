"""Provides ThreadHandler for asynchronous thread operations in Postgres
  . Utilizes psycopg3 for async database access
  . Delegates thread operations to PostgreSQL functions
  . Scopes thread operations by agent namespace (defaults to project_settings.rest_ref)
Functions/Classes:
  . ThreadHandler - Main class for thread management
Key Methods:
  . create_thread - Creates a new thread via PostgreSQL function
  . get_active_thread - Gets active thread and updates last_access_dtts
  . make_threads_inactive - Marks threads as inactive
  . get_stale_active_threads - Lists stale active threads eligible for inactivation
  . get_or_create_thread - Gets existing or creates new thread atomically
  . retain_thread - Sets retain_thread flag to true for active thread
"""

# %%
import psycopg
from config import project_settings


class ThreadHandler:
    def __init__(self, pool, agent: str = None):
        self.pool = pool
        self.agent = agent if agent is not None else project_settings.rest_ref

    async def create_thread(self, recipient):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM create_thread(%s, %s)
                        """,
                        (self.agent, recipient),
                    )
                    result = await cur.fetchone()
                    return result
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in create_thread: {e}")
            raise

    async def get_active_thread(self, recipient):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM get_active_thread(%s, %s)
                        """,
                        (self.agent, recipient),
                    )
                    result = await cur.fetchone()
                    return result
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in get_active_thread: {e}")
            raise

    async def make_threads_inactive(self, recipient):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT make_threads_inactive(%s, %s) as affected_rows
                        """,
                        (self.agent, recipient),
                    )
                    result = await cur.fetchone()
                    affected_rows = result[0] if result else 0
            return {"message": f"{affected_rows} thread(s) marked as inactive."}
        except psycopg.Error as e:
            print(f"Error in make_threads_inactive: {e}")
            raise

    async def get_stale_active_threads(self, stale_minutes: int = 5):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM get_stale_active_threads(%s, %s)
                        """,
                        (self.agent, stale_minutes),
                    )
                    results = await cur.fetchall()
                    return results
        except psycopg.Error as e:
            print(f"Error in get_stale_active_threads: {e}")
            raise

    async def get_or_create_thread(self, recipient):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM get_or_create_thread(%s, %s)
                        """,
                        (self.agent, recipient),
                    )
                    result = await cur.fetchone()
                    if result:
                        return result["thread_id"], result["was_created"]
                    return None, False
        except psycopg.Error as e:
            print(f"Error in get_or_create_thread: {e}")
            raise

    async def retain_thread(self, recipient):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT * FROM retain_thread(%s, %s)
                        """,
                        (self.agent, recipient),
                    )
                    result = await cur.fetchone()
                    return result
        except psycopg.Error as e:
            print(f"Error in retain_thread: {e}")
            raise


# %%
