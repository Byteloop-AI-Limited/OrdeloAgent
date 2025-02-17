# %%
from ordelo_datamodels.delivery_pymodels import RestaurantMaster, CustomerMaster, DeliveryDetail
from utils_common.db_utils.sbase_rest_ops import sbase_insert, sbase_delete, sbase_get, sbase_update, sbase_sync_update, sbase_sync_get

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

# %% wa_send_delivery_dispatch
_delivery_dispatch_webhook = {'delivery_dispatch': [{'dispatch_id': 16, 'order_number': 'test123', 'driver_id': '447448440754', 'driver_payout': 0.5, 'distance': 0.5, 'dt': '2025-02-12', 'ddts': '2025-02-12T13:58:31.030378', 'status': 'unassigned'}], 'delivery_detail': [{'order_number': 'test123', 'driver_id': 'DRIVER01', 'driver_payout': 25.5, 'distance': 10.5, 'rest_id': 'elai_basingstoke', 'rest_name': 'Elai Basingstoke', 'rest_lon': -1.08459464266133, 'rest_lat': 51.2625171747331, 'rest_address': 'Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY', 'customer_id': '447448440754', 'customer_name': '10hith', 'customer_lon': 0.0959000805415555, 'customer_lat': 51.3540813695372, 'customer_address': '27 Waring Drive, Orpington, BR66DN', 'status': 'Delivered', 'dt': '2025-02-12', 'ddts': '2025-02-12T13:44:30.865297'}]}
driver_id = _delivery_dispatch_webhook['delivery_dispatch'][0]['driver_id']
# %%
_delivery_detail = DeliveryDetail(**_delivery_dispatch_webhook['delivery_detail'][0])
_delivery_detail.driver_id
# %%
from utils_common.wa_send.wa_senders import _async_wa_client

# send restaurant location
await _async_wa_client.send_location(
    to=driver_id,
    latitude=_delivery_detail.rest_lat,
    longitude=_delivery_detail.rest_lon,
    name= f"{_delivery_detail.rest_name} Pick Up",
    address= _delivery_detail.rest_address
)

# send customer location
await _async_wa_client.send_location(
    to=driver_id,
    latitude=_delivery_detail.customer_lat,
    longitude=_delivery_detail.customer_lon,
    name=f"{_delivery_detail.customer_name} Drop Off",
    address=_delivery_detail.customer_address,
)

# %%
from pywa.types import SectionList, Section, SectionRow, Button, CallbackButton, Message, ButtonUrl

_async_wa_client.send_message(
    to=driver_id,
    text='make selection',
    buttons=[
        Button(title='Accept', callback_data=f'/jobAccepted'),
        Button(title='Decline', callback_data=f'/jobDeclined'),
    ]
)

# %%

