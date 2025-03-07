# %% Imports
import json
import logging
from contextlib import asynccontextmanager
import asyncio
import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from ordelo.agents.rider_agent import builder
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from pywa.types import Message
from pywa_async import WhatsApp, filters
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from ordelo_datamodels.masterdata_pymodels import RestaurantMaster, CustomerMaster
from utils_common.db_utils.sbase_pool_ops import insert_model_to_db, execute_sql_query
import uuid
from typing import Optional
from ordelo.agent_app_handlers import debug_state

from config import (
    logger,
    pg_settings,
    project_settings,
    waba_business_settings,
)
from utils_common.db_utils.sbase_rest_ops import sbase_get, sbase_call_function, sbase_update
from utils_common.thread_management import ThreadHandler
from ordelo.agent_app_handlers import (
    initial_handle_of_rider_response,
    init_ordelo_graph, 
    run_ordelo_graph, 
    process_dispatch_response_from_rider_sync
)
from watomation.routers import delivery_hooks, location_hooks

# %%
# Configure logging settings
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
# https://10hiths-app.up.railway.app/

# %% define fastapi
POOL_MIN_SIZE = 10
POOL_MAX_SIZE = 25

# %% Define Lifespan Events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the pool
    pool = AsyncConnectionPool(
        conninfo=pg_settings.db_uri,
        # min_size=20,
        # max_size=200,
        # max_lifetime=0,
        # max_idle=0,
        kwargs=pg_settings.connection_kwargs,
        open=False,
    )
    pool_sync = ConnectionPool(pg_settings.db_uri)
    pool_sync.open()
    
    # Explicitly open the pool
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    thread_handler = ThreadHandler(pool)
    # graph = builder.compile(checkpointer=checkpointer)
    graph = builder.compile(checkpointer=MemorySaver())

    # Store it in the app state
    app.state.pool: AsyncConnectionPool = pool
    app.state.pool_sync: ConnectionPool = pool_sync
    app.state.client = pg_settings.client
    app.state.checkpointer = checkpointer
    app.state.thread_handler = thread_handler
    app.state.graph: CompiledStateGraph = graph

    # in memory data
    # app.state.DELIVERY_INFLIGHT = await sbase_get("delivery_inflight")

    # Yield to start the application
    try:
        yield
    finally:
        # Close the pool on shutdown
        await pool.close()

# %% Define Fastapi app with lifespan and routers

app = FastAPI(title="OrdeloAgent", lifespan=lifespan)
app.include_router(delivery_hooks.router, prefix="/delivery-hooks")
app.include_router(location_hooks.router, prefix="/location-hooks")

recipient='447448440754'

# %% Local runs
if __name__ == "__main__":
    from dotenv import load_dotenv

    project_root = project_settings.project_root
    load_dotenv(f"{project_root}/.env")
    logger.info("Starting OrdeloAgent locally ...")

    wa: WhatsApp = WhatsApp(
        token=waba_business_settings.token,
        server=app,
        verify_token=waba_business_settings.verify_token,
        phone_id=waba_business_settings.phone_id,
        # callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
    )
else:
    wa: WhatsApp = WhatsApp(
        token=waba_business_settings.token,
        server=app,
        verify_token=waba_business_settings.verify_token,
        phone_id=waba_business_settings.phone_id,
        # callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
    )
    
# %% details
@app.get("/details")
async def get_details():
    business_phone_number = await wa.get_business_phone_number()
    phone_id = waba_business_settings.phone_id
    phone_num = business_phone_number.display_phone_number
    bus_name = business_phone_number.verified_name
    callback_url_on_waba = business_phone_number.webhook_configuration["application"]
    callback_url = waba_business_settings.callback_url

    return {
        "phone_id": str(phone_id),
        "display_phone_num": phone_num,
        "verified_name": bus_name,
        "callback_url": callback_url,
        "callback_url_on_waba": callback_url_on_waba
    }

# %% debug state 
@app.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    graph = app.state.graph
    pool = app.state.pool
    debug_stack = await debug_state(recipient, graph, pool)
    return debug_stack
# %% WA Overrides - reset, payment complete, reservation confirmation

# TEST_DELIVERY = filters.contains("/testdelivery", ignore_case=True)
TEST_DELIVERY = filters.contains("/test", ignore_case=True)
LIVE_LOCATION = filters.contains("/live", ignore_case=True)

WHEN_RESET = filters.contains("/reset", ignore_case=True)
PAYMENT_COMPLETE = filters.contains("/paid", ignore_case=True)
RESERVATION_CONFIRMED = filters.contains("/confirm", ignore_case=True)
IS_DISPATCH_RESPONSE_DECLINED = filters.contains("/dispatchResponse", ignore_case=False) & filters.contains("status: declined", ignore_case=False)
IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)

# %% TestDelivery

@wa.on_message(LIVE_LOCATION)
async def live_location(wa: WhatsApp, msg: Message):
    #toDo this needs to go
    recipient = msg.sender
    logger.info("liv_location requested ...")
    
    _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)

    order_number = _inflight[0]['order_number']
    pool = app.state.pool
    # live location logic, reused
    query = """
    SELECT 
        lat, 
        lon
    FROM rider_location LOC INNER JOIN delivery_inflight DI
    ON LOC.rider_id = DI.rider_id
    WHERE LOC.order_number = %s
    ORDER BY tst DESC
    LIMIT 1
    """
    result = await execute_sql_query(pool, query, (order_number,))
    if result is None:
        return None
    
    lat, lon = result[0]
    
    logger.info(f"lat:{lat}, lon:{lon}")

    live_map_url=f"https://maps.google.com/?q=Order('{order_number}')@{lat},{lon}"
    logger.info(live_map_url)
    await wa.send_message(
        to=recipient, 
        text=live_map_url
        )

# %% test delivery
@wa.on_message(TEST_DELIVERY)
async def test_delivery(wa: WhatsApp, msg: Message):
    pool = app.state.pool
    order_number = uuid.uuid4().hex
    # %%
    warren_road = RestaurantMaster(
    **{
        "rest_id": "warren_road", 
        "rest_name": "Warren Road", 
        "rest_lon": 0.09076387564540894,
        "rest_lat": 51.36020627498843,
        "rest_address": "Warren Rd, Orpington BR6 6JF",
        "town": "Orpington"}
    )
    if msg.text.endswith('r'):
        elai_customer = CustomerMaster(
            **{
                "customer_id": "447446933210",
                "customer_name": "Rahul",
                "customer_lon": 0.09807413931483216,
                "customer_lat": 51.361305286779476,
                "customer_address": "29 Hollywell Close, BR69XP",
            })
    else:
        elai_customer = CustomerMaster(
            **{
                "customer_id": "447448440754",
                "customer_name": "10hith",
                "customer_lon": 0.09590008054155555,
                "customer_lat": 51.35408136953724,
                "customer_address": "27 Waring Drive, Orpington, BR66DN",
            })

    insert_data = {
        "order_number": order_number,
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
    # %% DB operations
    # Cleanup - update dispatch complete
    open_dispatch = await sbase_get(table_name='delivery_dispatch', status='assigned')
    for dispatch in open_dispatch:
        await sbase_call_function(function_name='dispatch_complete_func', input_args={'p_dispatch_id': dispatch['dispatch_id']})

    # Cleanup - delete from rider_location_event
    delete_old_location_events = f"DELETE FROM rider_location_event WHERE order_number = '{order_number}'"
    await execute_sql_query(pool, query=delete_old_location_events)
    
    # Create delivery detail
    await insert_model_to_db(pool, table_name="delivery_detail", model_instance=_delivery_detail)
    
    # delete existing order and insert new one
    # delete_old_order = f"DELETE FROM delivery_detail WHERE order_number = '{order_number}'"
    # await execute_sql_query(pool, query=delete_old_order)

    # Update existing dispatch status and insert new one
    # update_dispatch_status_q = f"UPDATE delivery_dispatch SET status = 'completed' WHERE order_number = '{order_number}'"
    # await execute_sql_query(pool, query=update_dispatch_status_q)

    # clear_inflight_q = "delete from delivery_inflight;"
    # await execute_sql_query(pool, query=clear_inflight_q)

    # Create a initial delivery dispatchs
    # next_available_rider_q = f"SELECT * FROM get_available_riders('{order_number}');"
    # available_riders = await execute_sql_query(pool, query=next_available_rider_q)
    # initial_rider_id = available_riders[0][0]
    
    # initial_delivery_dispatch = {
    #     'order_number': order_number,
    #     'rider_id': initial_rider_id,
    #     'rider_payout': 0.5,
    #     'distance': 0.5,
    #     'status': 'unassigned'
    # }
    
    # _delivery_dispatch = DeliveryDispatch(**initial_delivery_dispatch)
    # await insert_model_to_db(pool, table_name="delivery_dispatch", model_instance=_delivery_dispatch)

    
# %% Reset
@wa.on_message(WHEN_RESET)
async def reset_thread(wa: WhatsApp, msg: Message):
    logger.info("=============== reset the thread ===============")
    recipient = msg.from_user.wa_id
    thread_handler = app.state.thread_handler
    
    _inflight = await sbase_get("delivery_inflight", rider_id=recipient)
    
    # Exit if there is no active dispatch 
    if len(_inflight) != 0:
        dispatch_id = _inflight[0]['dispatch_id']
        await sbase_call_function(function_name='dispatch_complete_func', input_args={'p_dispatch_id': dispatch_id})

    await thread_handler.make_threads_inactive(from_number=recipient)
    await wa.send_message(to=recipient, text="Starting new conversation")


# %% WA Handlers - Callback
@wa.on_callback_button(IS_DISPATCH_RESPONSE)
async def dispatch_response(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch. This is a blocking operation. Entry point into the graph.
    """
    client = app.state.client
    # logger.info(msg)
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
    
    dispatch_id = callback_data['dispatch_id']
    order_number = callback_data['order_number']
    rider_response = callback_data['status']


    # await sbase_update(table_name='delivery_dispatch', )

# %% WA Handlers - Callback Old
# @wa.on_callback_button(IS_DISPATCH_RESPONSE)
# def callback_selection(wa: WhatsApp, msg: Message):
#     """
#     Rider's response to delivery dispatch. This is a blocking operation. Entry point into the graph.
#     """ 
#     # logger.info(msg)
#     recipient = msg.sender
#     callback_data: dict = json.loads(msg.data)
#     callback_data['rider_id']=recipient
#     logger.info(callback_data)
    
#     dispatch_id = callback_data['dispatch_id']

#     # start db operations in sync context
#     pool_sync = app.state.pool_sync
#     pool = app.state.pool
#     graph = app.state.graph

#     d_detail_dict: DeliveryDetail = process_dispatch_response_from_rider_sync(
#         pool_sync=pool_sync,
#         rider_id=recipient,
#         callback_data=callback_data
#     )
    
#     if isinstance(d_detail_dict, str):
#         # either declined or job already taken
#         return 

#     # update delivery detail since the fetch was from before the table update
#     d_detail_dict['dispatch_id'] = dispatch_id
#     d_detail_dict['rider_id'] = recipient
#     d_detail_dict['status'] = 'assigned'


#     # Create the model instance
#     d_detail = DeliveryDetail(**d_detail_dict)
    
#     logger.info(d_detail_dict)

#     # Initiate the graph execution as background task
#     asyncio.create_task(init_ordelo_graph(graph, pool, d_detail))

# %%


@wa.on_message()
async def process_wa_msg(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    pool = app.state.pool
    graph = app.state.graph
    thread_handler = app.state.thread_handler

    thread_row = await thread_handler.get_active_thread(recipient)

    # exit if there is not active delivery
    if thread_row is None:
        await wa.send_message(to=recipient, text="You have no active delivery")
        return

    # Run the graph
    await run_ordelo_graph(msg, graph, pool)
# %%
if __name__ == "__main__":
    uvicorn.run("watomation.fapp_ordelo_agent:app", host="0.0.0.0", port=3100, reload=True)
