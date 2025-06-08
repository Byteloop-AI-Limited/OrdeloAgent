# %%

import httpx
import asyncio

# from utils_common.order_management.delivery_pymodels import DeliverySummary
from config import client_ordelo

# %%
p_order_number = "WREN-HFIB-21"
delivery_summary = (
    client_ordelo.table("delivery_summary")
    .select("*")
    .eq("order_number", p_order_number)
    .limit(1)
    .execute()
    .data[0]
)
delivery_summary
# %%


async def post_rider_event_inflight(delivery_summary: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://live-track.byteloop.ai/rider-event-hooks/rider-inflight",
            json=delivery_summary,
        )
        print("Status code:", response.status_code)
        print("Response JSON:", response.json())


await post_rider_event_inflight(delivery_summary)


# %%
async def post_rider_event_restaurant_cc(delivery_summary: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://live-track.byteloop.ai/rider-event-hooks/on-restaurant-cc",
            json=delivery_summary,
        )
        print("Status code:", response.status_code)
        print("Response JSON:", response.json())


await post_rider_event_restaurant_cc(delivery_summary)


# %%
async def post_rider_event_customer_cc(delivery_summary: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://live-track.byteloop.ai/rider-event-hooks/on-customer-cc",
            json=delivery_summary,
        )
        print("Status code:", response.status_code)
        print("Response JSON:", response.json())


await post_rider_event_customer_cc(delivery_summary)
# %%
# Example usage:
# delivery = DeliverySummary(**your_kwargs_here)
# asyncio.run(post_delivery_summary(delivery))
