# %%
from pywa_async import WhatsApp
from config import logger
from pywa.types import Message
import json
# project modules
from watomation.init_app_state import get_app_state
from ordelo.agent_app_handlers import initial_handle_of_rider_response


async def dispatch_response(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch. This is a blocking operation. Entry point into the graph.
    """
    # get app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = get_app_state()
    
    recipient = msg.sender
    callback_data: dict = json.loads(msg.data)
    # remove command from callback data and add rider_id
    callback_data.pop('command') 
    callback_data['rider_id']=recipient

    order_status = client.table("delivery_detail")\
        .select("status")\
        .eq("order_number", callback_data['order_number'])\
        .execute()
    
    if len(order_status.data) == 0:
        logger.error("No delivery detail found for order number: {}".format(callback_data['order_number']))
        await wa.send_message(
                        to=recipient,
                        text='Sorry, This job is no longer available'
                    )
        return

    order_status=order_status.data[0]
    await initial_handle_of_rider_response(order_status, callback_data)
