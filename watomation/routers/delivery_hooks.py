from fastapi import APIRouter, Request
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliveryDispatch
from utils_common.wa_send.wa_senders import wa_send_delivery_dispatch_request_to_rider
from loguru import logger

# %%
# https://live-track.byteloop.ai/delivery-hooks
router = APIRouter(tags=["delivery_hooks"])

@router.get("/",
    summary="Root Endpoint",
    description="Returns a simple message to verify the delivery hooks router is working",
    response_description="A welcome message",
    responses={
        200: {
            "description": "Successfully retrieved welcome message",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Delivery Hooks Router"
                    }
                }
            }
        }
    }
)
async def root():
    return {"message": "Delivery Hooks Router"}


@router.post("/delivery-dispatch",
    summary="Process Delivery Dispatch",
    description="""
    Processes a new delivery dispatch request and notifies the assigned rider.
    
    This endpoint:
    1. Receives delivery dispatch and detail information
    2. Validates the payload contains required information
    3. Sends a WhatsApp notification to the assigned rider for job acceptance
    """,
    response_description="Status of the dispatch operation and the processed data",
    responses={
        200: {
            "description": "Successfully processed dispatch request",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "delivery_dispatch": [{"dispatch_id": "123", "rider_id": "456"}],
                            "delivery_detail": [{"order_number": "789", "customer_name": "John Doe"}]
                        }
                    }
                }
            }
        }
    }
)
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

    # if delivery_dispatch or detail is not in payload, logger.error
    if len(payload['delivery_dispatch']) == 0 or len(payload['delivery_detail']) == 0:
        logger.error("no delivery_dispatch or detail found for dispatch: {}".format(payload))
        return {"status": "error", "data": payload}

    # extract from payload
    rider_id = payload['delivery_dispatch'][0]['rider_id']
    dispatch_id = payload['delivery_dispatch'][0]['dispatch_id']
    delivery_detail = DeliveryDetail(**payload['delivery_detail'][0])
    
    await wa_send_delivery_dispatch_request_to_rider(
        recipient = rider_id, 
        delivery_detail=delivery_detail,
        dispatch_id=dispatch_id
    )
    
    return {"status": "success", "data": payload}



@router.post("/delivery-inflight-sync",
    summary="Sync Delivery Inflight Data",
    description="Synchronizes the current in-flight delivery data with the system",
    response_description="Status of the sync operation and the processed data",
    responses={
        200: {
            "description": "Successfully synced delivery inflight data",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {"delivery_inflight": []}
                    }
                }
            }
        }
    }
)
async def delivery_inflight_sync(request: Request):
    # ToDo - This is not required anymore

    payload = await request.json()

    # Update the FastAPI state variable
    # request.app.state.DELIVERY_INFLIGHT = payload['delivery_inflight']
        
    return {"status": "success", "data": payload}


@router.get("/delivery-inflight-sync",
    summary="Get Delivery Inflight Data",
    description="Retrieves the current in-flight delivery data from the system state",
    response_description="Current delivery inflight data",
    responses={
        200: {
            "description": "Successfully retrieved delivery inflight data",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": []
                    }
                }
            }
        }
    }
)
async def delivery_inflight_sync_get(request: Request):
    return {"status": "success", "data": request.app.state.DELIVERY_INFLIGHT}