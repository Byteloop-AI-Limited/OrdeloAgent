# %%
from config import pg_settings
from utils_common.db_utils.sbase_rest_ops import sbase_get

client = pg_settings.client

# %%
summary = await sbase_get(table_name="delivery_summary", order_number="test123")
print(summary)

# %%
client.rpc(
    "init_delivery", {"p_cust_id": "447448440754", "p_order_number": "WREN-1234-123"}
).execute()
