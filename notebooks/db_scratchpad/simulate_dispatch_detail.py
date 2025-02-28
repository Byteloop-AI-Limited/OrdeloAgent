# %%
from ordelo_datamodels.delivery_pymodels import RestaurantMaster, CustomerMaster, DeliveryDetail
from utils_common.db_utils.sbase_rest_ops import sbase_insert, sbase_delete, sbase_get, sbase_update, sbase_sync_update, sbase_sync_get

# %%
# %% Update detail to accepted to test the tigger
await sbase_update(
                update_fields={"status": "unassigned"},
                table_name="delivery_detail",
                order_number='test123'
            )
# %%  
sbase_sync_update(
                update_fields={"status": "assigned"},
                table_name="delivery_detail",
                order_number='test123'
            )

# %%
# delivery_dispatch = {
#     'order_number': 'test123',
#     'rider_id': "447448440754",
#     'rider_payout': 0.5,
#     'distance': 0.5,
#     'status': 'unassigned'
# }
# await sbase_insert("delivery_dispatch", delivery_dispatch)
# %% Create test delivery

warren_road = RestaurantMaster(
    **{
        "rest_id": "warren_road", 
        "rest_name": "Warren Road", 
        "rest_lon": 0.09076387564540894,
        "rest_lat": 51.36020627498843,
        "rest_address": "Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY"}
    )

elai_customer = CustomerMaster(
    **{
        "customer_id": "447448440754",
        "customer_name": "10hith",
        "customer_lon": 0.09590008054155555,
        "customer_lat": 51.35408136953724,
        "customer_address": "27 Waring Drive, Orpington, BR66DN",
    })

insert_data = {
    "order_number": "test123",
    "rider_payout": 5.50,
    "distance": 10.5,
    "status": "unassigned"
}

# elai_customer = CustomerInfo(**insert_data)
_delivery_detail = DeliveryDetail(
    **insert_data, 
    **warren_road.model_dump(),
    **elai_customer.model_dump()
    )
_delivery_detail

# %% 
_delivery_detail.google_maps_url
# %%
await sbase_insert("delivery_detail", _delivery_detail.model_dump())

# %%
await sbase_delete("delivery_detail", order_number="test123")


# %% Delivery Dispatch
delivery_dispatch = {
    'order_number': 'test123',
    'driver_id': "447448440754",
    'driver_payout': 0.5,
    'distance': 0.5,
    'status': 'unassigned1'
}
await sbase_insert("delivery_dispatch", delivery_dispatch)

# %%
await sbase_get("delivery_dispatch", dispatch_id=15)

# %% With pool
from config import pg_settings
from psycopg_pool import ConnectionPool
from datetime import datetime, timedelta
from ordelo_datamodels.delivery_pymodels import RestaurantMaster, CustomerMaster, DeliveryDetail

pool = ConnectionPool(pg_settings.db_uri)

def insert_model_to_db(pool, table_name, model_instance):
    """
    Insert a Pydantic model instance into a database table.
    
    Args:
        pool: Database connection pool
        table_name: Name of the target database table
        model_instance: Pydantic model instance to insert
        
    Returns:
        None
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Get model fields dynamically
            model_data = model_instance.model_dump()
            columns = list(model_data.keys())
            placeholders = ', '.join(['%s'] * len(columns))
            columns_str = ', '.join(columns)
            
            # Build SQL query dynamically
            query = f"""
                INSERT INTO {table_name} ({columns_str})
                VALUES ({placeholders})
            """
            
            # Execute with values in the correct order
            values = tuple(model_data.values())
            cur.execute(query, values)
            conn.commit()

# Example usage
insert_model_to_db(pool, 'delivery_detail', _delivery_detail)

# %%
warren_road = RestaurantMaster(
    **{
        "rest_id": "warren_road", 
        "rest_name": "Warren Road", 
        "rest_lon": 0.09076387564540894,
        "rest_lat": 51.36020627498843,
        "rest_address": "Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY"}
    )

elai_customer = CustomerMaster(
    **{
        "customer_id": "447448440754",
        "customer_name": "10hith",
        "customer_lon": 0.09590008054155555,
        "customer_lat": 51.35408136953724,
        "customer_address": "27 Waring Drive, Orpington, BR66DN",
    })

insert_data = {
    "order_number": "test1234",
    "rider_payout": 5.50,
    "distance": 10.5,
    "status": "unassigned"
}

# elai_customer = CustomerInfo(**insert_data)
_delivery_detail = DeliveryDetail(
    **insert_data, 
    **warren_road.model_dump(),
    **elai_customer.model_dump()
    )
_delivery_detail.model_dump()

# %%

# with pool.connection() as conn:
#     with conn.cursor() as cur:
#         # Get model fields dynamically
#         model_data = _delivery_detail.model_dump()
#         columns = list(model_data.keys())
#         placeholders = ', '.join(['%s'] * len(columns))
#         columns_str = ', '.join(columns)
        
#         # Build SQL query dynamically
#         query = f"""
#             INSERT INTO delivery_detail ({columns_str})
#             VALUES ({placeholders})
#         """
        
#         # Execute with values in the correct order
#         values = tuple(model_data.values())
#         cur.execute(query, values)
#         conn.commit()

# %%
from utils_common.db_utils.sbase_pool_ops import execute_sql_query
# %%

execute_sql_query()