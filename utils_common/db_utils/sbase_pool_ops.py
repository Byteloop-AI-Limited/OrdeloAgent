# %%
"""
Async helper functions for generic Postgres CRUD using `psycopg_pool.AsyncConnectionPool`.
    . `insert_model_to_db` dynamically builds INSERT from a Pydantic instance
    . `execute_sql_query` runs arbitrary SQL with optional parameters and commit handling
"""

from config import pg_settings


async def insert_model_to_db(table_name, model_instance):
    """
    Insert a Pydantic model instance into a database table.

    Args:
        table_name: Name of the target database table
        model_instance: Pydantic model instance to insert

    Returns:
        None
    """
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Get model fields dynamically
            model_data = model_instance.model_dump()
            columns = list(model_data.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            columns_str = ", ".join(columns)

            # Build SQL query dynamically
            query = f"""
                INSERT INTO {table_name} ({columns_str})
                VALUES ({placeholders})
            """

            # Execute with values in the correct order
            values = tuple(model_data.values())
            await cur.execute(query, values)
            await conn.commit()


async def execute_sql_query(query: str, params=None):
    """
    Execute a SQL query using the database connection pool.

    Args:
        query: SQL query string to execute
        params: Optional parameters for the query (default: None)

    Returns:
        List of query results if the query returns data, otherwise None
    """
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Execute the query with optional parameters
            if params:
                await cur.execute(query, params)
            else:
                await cur.execute(query)

            # Commit changes if the query modifies data
            if (
                query.strip()
                .lower()
                .startswith(("insert", "update", "delete", "create", "alter", "drop"))
            ):
                await conn.commit()

            # Fetch results if the query returns data
            if cur.description:
                return await cur.fetchall()

            return None
