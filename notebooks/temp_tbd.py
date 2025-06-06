# %%
from config import pg_settings

client = pg_settings.client
pg_settings.db_uri

# %%
pg_settings.client.table("rider_location").select("*").like(
    "order_number", "91827398172-%"
).limit(1).execute().data

# %%
client.table("delivery_option").select("order_number").like(
    "order_number", "WREN-TEST-%"
).order("id", desc=True).limit(1).execute().data[0]["order_number"]
