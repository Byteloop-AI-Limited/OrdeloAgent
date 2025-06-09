# %%

import httpx
import asyncio

# from utils_common.order_management.delivery_pymodels import DeliverySummary
from config import client_ordelo, get_webhook_url


# %%
async def post_rider_event_restaurant_cc(order_number: str):
    rest_ref = order_number.split("-")[0]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            get_webhook_url(rest_ref, "rider-rest-cc") + "/" + order_number,
            json={},
        )
        print("Status code:", response.status_code)
        print("Response JSON:", response.json())


await post_rider_event_restaurant_cc("WREN-HFIB-21")


# %%
async def post_rider_event_customer_cc(order_number: str):
    rest_ref = order_number.split("-")[0]
    async with httpx.AsyncClient() as client:
        response = await client.post(
            get_webhook_url(rest_ref, "rider-cust-cc") + "/" + order_number,
            json={},
        )
        print("Status code:", response.status_code)
        print("Response JSON:", response.json())


await post_rider_event_customer_cc("WREN-HFIB-21")
# %%
# Example usage:
# delivery = DeliverySummary(**your_kwargs_here)
# asyncio.run(post_delivery_summary(delivery))
