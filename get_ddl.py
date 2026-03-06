import asyncio
from utils_common.db_utils.sbase_pool_ops import execute_sql_query

async def main():
    query = """
    SELECT column_name, data_type, character_maximum_length, column_default, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'elas_menu'
    ORDER BY ordinal_position;
    """
    rows = await execute_sql_query(query)
    for row in rows:
        print(row)

asyncio.run(main())
