# %%
from utils_common.db_utils.sbase_rest_ops import sbase_get
from datetime import datetime
from psycopg_pool import ConnectionPool
from datetime import datetime, timezone, timedelta
from config import pg_settings
# %%
pool = ConnectionPool(pg_settings.db_uri)

# %%
with pool.connection() as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            select * from rider_location where rider_id=%s and order_number=%s and dtts >= %s
            """,
            ('447448440754', 'test123', datetime.now() - timedelta(days=1))
        )
        location_data = cur.fetchone()

print(location_data)
# %%
location_data =await sbase_get("rider_location", 
rider_id='447448440754', 
order_number='test123', 
dtts__gte=datetime.now()
)
if location_data:
    print(location_data)
else:
    print("No data found")
    
# %%
# %%