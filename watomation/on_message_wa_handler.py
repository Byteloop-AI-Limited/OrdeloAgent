# %%
from pywa_async import WhatsApp, types
from config import logger, _sync_wa_client
from pywa.types.flows import FlowRequest, FlowResponse
from pywa.types import Message
import uuid
# project modules
from watomation.init_app_state import get_app_state
from utils_common.db_utils.sbase_rest_ops import sbase_get, sbase_call_function
from utils_common.db_utils.sbase_pool_ops import insert_model_to_db, execute_sql_query
from ordelo_datamodels.masterdata_pymodels import RestaurantMaster, CustomerMaster
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from ordelo.agent_app_handlers import run_ordelo_graph
from pywa.types.flows import FlowActionType
from pywa.types import FlowButton

# %% Run graph on msg
async def process_wa_msg(wa: WhatsApp, msg: Message):
    # Get app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = get_app_state()
    
    recipient = msg.sender

    thread_row = await thread_handler.get_active_thread(recipient)

    # exit if there is not active delivery
    if thread_row is None:
        await wa.send_message(to=recipient, text="You have no active delivery")
        return

    # Run the graph
    await run_ordelo_graph(msg, graph, pool)

# %% Reset
async def reset_thread(wa: WhatsApp, msg: Message):
    # Get app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = get_app_state()
    
    logger.info("=============== reset the thread ===============")
    recipient = msg.from_user.wa_id
    
    _inflight = await sbase_get("delivery_inflight", rider_id=recipient)
    
    # Exit if there is no active dispatch 
    if len(_inflight) != 0:
        dispatch_id = _inflight[0]['dispatch_id']
        await sbase_call_function(function_name='dispatch_complete_func', input_args={'p_dispatch_id': dispatch_id})

    await thread_handler.make_threads_inactive(from_number=recipient)
    await wa.send_message(to=recipient, text="Starting new conversation")

# %% Test Delivery
async def test_delivery(wa: WhatsApp, msg: Message):
    # Get app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = get_app_state()

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
        "vehicle_type": "car",
        "distance": 10.5,
        "status": "unassigned"
    }

    # elai_customer = CustomerInfo(**insert_data)
    _delivery_detail = DeliveryDetail(
        **insert_data, 
        **warren_road.model_dump(),
        **elai_customer.model_dump()
        )
    # DB operations
    # Cleanup - update dispatch complete
    open_dispatch = await sbase_get(table_name='delivery_dispatch', status='assigned')
    for dispatch in open_dispatch:
        await sbase_call_function(function_name='dispatch_complete_func', input_args={'p_dispatch_id': dispatch['dispatch_id']})

    # Cleanup - delete from rider_location_event
    delete_old_location_events = f"DELETE FROM rider_location_event WHERE order_number = '{order_number}'"
    await execute_sql_query(pool, query=delete_old_location_events)
    
    # Create delivery detail
    await insert_model_to_db(pool, table_name="delivery_detail", model_instance=_delivery_detail)


# %% Test flow
async def test_flow(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    _sync_wa_client.send_message(
        to=recipient,
        text="Update your address details",
        buttons=FlowButton(
            title="Update Details",
            flow_id=955259853427256,  # The `static_flow` flow id from above
            flow_token="123",
            # mode=FlowStatus.DRAFT,
            flow_action_type=FlowActionType.NAVIGATE,
            flow_action_screen="START", # The screen id to open when the user clicks the button
            flow_action_payload={
                "flow_name": "Postcode Search",
                "customer_id": "44744123123123",
                "postcode_init": "BR6 6DN"
            }
        )
    )
# %%
# %% live_location
async def live_location(wa: WhatsApp, msg: Message):
    #toDo this needs to go
    # get app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = get_app_state()
    recipient = msg.sender
    logger.info("liv_location requested ...")
    
    _inflight = await sbase_get(table_name="delivery_inflight", rider_id=recipient)
    
    if len(_inflight) == 0:
        await wa.send_message(to=recipient, text="Location not available. You have no active delivery")
        return
    
    order_number = _inflight[0]['order_number']
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
# %% Only references
def handle_callback_button(wa: WhatsApp, clb: types.CallbackButton):
    print(clb.data)


def on_sign_up_request(_: WhatsApp, request: FlowRequest) -> FlowResponse | None:
    logger.info(request)
    logger.info(request.data)
    
    if request.has_error:
        logger.error("Flow request has error: %s", request.data)
        return FlowResponse(
            data={"acknowledged": True}
        )

    return FlowResponse(
        version=request.version,
        screen="START",
        data={
            "customer_name": "John Doe",
            "customer_id": "44744123123123",
            "address": "one kingdom street"
        },
    )
