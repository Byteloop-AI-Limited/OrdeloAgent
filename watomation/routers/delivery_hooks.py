from fastapi import APIRouter, Request
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from utils_common.wa_send.wa_senders import wa_send_delivery_dispatch
from loguru import logger

# %%
# https://live-track.byteloop.ai/delivery-hooks
router = APIRouter(tags=["delivery_hooks"])

@router.get("/")
async def root():
    return {"message": "Delivery Hooks Router"}


@router.post("/delivery_dispatch")
async def delivery_dispatch_hook(request: Request):
    payload = await request.json()
    driver_id = payload['delivery_dispatch'][0]['driver_id']
    dispatch_id = payload['delivery_dispatch'][0]['dispatch_id']
    delivery_detail = DeliveryDetail(**payload['delivery_detail'][0])
    
    await wa_send_delivery_dispatch(
        recipient = driver_id, 
        delivery_detail=delivery_detail,
        dispatch_id=dispatch_id
        )

    # print(f"Received delivery dispatch webhook: {payload}")
    return {"status": "success", "data": payload}


@router.post("/delivery_detail_update")
async def delivery_detail_update_hook(request: Request):
    # Access app state through request.app.state
    # graph = request.app.state.graph  # Example of accessing graph from app state
    
    payload = await request.json()
    logger.success(".......Delivery Detail Update......")
    print(payload)
    # Use the graph or other state objects as needed
    return {"status": "success", "data": payload}
