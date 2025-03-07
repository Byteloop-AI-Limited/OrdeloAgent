# %%
from config import pg_settings
client = pg_settings.client


# %%
response = client.table("delivery_dispatch")\
    .update({
        "status": "declined"
    })\
    .eq("dispatch_id","143")\
    .execute()
# %%
sample_list=[]
sample_list[0]
# %% dispatch insert

payload = {'command': '/dispatchResponse', 'order_number': '81d94ed549684dd0826c21bb75b0d055', 'dispatch_id': 141, 'status': 'accepted', 'rider_id': '447448440754'}
payload.pop('command')
payload
# response = client.table("delivery_dispatch").insert(payload).execute()
# response

# %%
from config import logger, _async_wa_client

async def initial_handle_of_rider_response(order_status, callback_data):
    if len(order_status) == 0:
        logger.error("No delivery detail found for order number: {}".format(callback_data['order_number']))
        await _async_wa_client.send_message(
                        to=callback_data['rider_id'],
                        text='Sorry, This job is no longer available'
                    )  
        return


# %%
import asyncio
import nest_asyncio
nest_asyncio.apply()

async def run_query():
    response = await async_client.table("delivery_dispatch").select("*").execute()
    print(response.data)

# Run the async function
asyncio.run(run_query())


print(response.data)
# %%
response = async_client.table("delivery_detail")\
    .select("*")\
    .eq("order_number", "0f9d9e9b75fa4db7a1e34e0c53c6b986")\
    .execute()