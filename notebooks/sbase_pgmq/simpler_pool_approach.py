# %%
from utils_common.db_utils.sbase_rest_ops import sbase_update, sbase_insert, sbase_delete
from config import pg_settings
from ordelo_datamodels.delivery_pymodels import DeliveryDispatch

supabase = pg_settings.client

# %% Create sample dispatches
_dispatch_rows = [{
    "order_number": "0f9d9e9b75fa4db7a1e34e0c53c6b986",
    "rider_id": "447448440754",
    "rider_payout": 5.00,
    "distance": 1.5,
    "status": "accepted"
}, {
    "order_number": "0f9d9e9b75fa4db7a1e34e0c53c6b986",
    "rider_id": "447448440754",
    "rider_payout": 5.00,
    "distance": 1.5,
    "status": "accepted"
}]


# %%
response = supabase.table("delivery_dispatch").insert(_dispatch_rows).execute()
response
# %%

# %%
# %% update table
supabase.table("delivery_dispatch")\
    .update({"status": "missed"})\
    .in_("order_number", ['0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a'])\
    .execute()

await sbase_update(
    table_name='delivery_dispatch', 
    update_fields={"status": "accepted"}, 
    order_number=_dispatch_rows[0]['order_number']
    )

await sbase_update(
    table_name='delivery_dispatch', 
    update_fields={"status": "accepted"}, 
    order_number=_dispatch_rows[1]['order_number']
    )
# %%
await sbase_delete(table_name='delivery_dispatch', order_number=_dispatch_rows[0]['order_number'])
await sbase_delete(table_name='delivery_dispatch', order_number=_dispatch_rows[1]['order_number'])


# %% Job to run every 5 seconds