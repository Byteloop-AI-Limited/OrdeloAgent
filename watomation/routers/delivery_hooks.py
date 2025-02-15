from fastapi import APIRouter, Request
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliveryDispatch
from utils_common.wa_send.wa_senders import wa_send_delivery_dispatch
from loguru import logger
from ordelo.agent_app_handlers import init_ordelo_graph

# %%
# https://live-track.byteloop.ai/delivery-hooks
router = APIRouter(tags=["delivery_hooks"])

@router.get("/")
async def root():
    return {"message": "Delivery Hooks Router"}


@router.post("/delivery-dispatch")
async def delivery_dispatch_hook(request: Request):
    """
    On insert into delivery_dispatch table, trigger delivery dispatch webhook.

    This endpoint processes a delivery dispatch request by extracting 
    rider ID, dispatch ID, and delivery details from the request payload. 
    It then uses these details to send a dispatch message via WhatsApp.

    Args:
        request (Request): The HTTP request object containing JSON payload.

    Returns:
        dict: A dictionary with the status of the operation and the original 
              payload data.
    """
    payload = await request.json()
    if len(payload['delivery_detail']) == 0:
        logger.error("no delivery_detail found for dispatch: {}".format(payload))
        return {"status": "error", "data": payload}

    # todo
    delivery_dispatch = DeliveryDispatch(**payload['delivery_dispatch'][0])
    delivery_detail = DeliveryDetail(**payload['delivery_detail'][0])
    
    await wa_send_delivery_dispatch(
        recipient = delivery_dispatch.rider_id, 
        delivery_detail=delivery_detail,
        dispatch_id=delivery_dispatch.dispatch_id
    )
    
    return {"status": "success", "data": payload}


@router.post("/delivery-detail-update")
async def delivery_detail_update_hook(request: Request):
    # Initialize the graph

    graph = request.app.state.graph
    pool = request.app.state.pool


    payload = await request.json()
    d_detail = DeliveryDetail(**payload['delivery_detail'][0])
    d_dispatch = DeliveryDispatch(**payload['delivery_dispatch'][0])
    
    await init_ordelo_graph(graph, pool, d_detail, d_dispatch)
    
    # Use the graph or other state objects as needed
    return {"status": "success", "data": payload}
