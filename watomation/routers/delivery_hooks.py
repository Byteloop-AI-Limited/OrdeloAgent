from fastapi import APIRouter, Request
from ordelo_datamodels.delivery_pymodels import DeliveryDetail

from config import logger, _async_wa_client
from pywa.types import Button
from pywa_async import WhatsApp
from datetime import datetime, timedelta
import json
# %%
# https://live-track.byteloop.ai/delivery-hooks
router = APIRouter(tags=["delivery_hooks"])

# %% supporting functions
async def wa_send_delivery_dispatch_request_to_rider(
    recipient: str,
    delivery_detail: DeliveryDetail,
    dispatch_id: int,
    _async_wa_client: WhatsApp = _async_wa_client
):
    order_number = delivery_detail.order_number

    accept_pl = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
        "status": "accepted"
    }

    decline_pl = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
        "status": "declined"
    }

    # send restaurant location
    # await _async_wa_client.send_location(
    #     to=recipient,
    #     latitude=delivery_detail.rest_lat,
    #     longitude=delivery_detail.rest_lon,
    #     name= f"{delivery_detail.rest_name} Pick Up",
    #     address= delivery_detail.rest_address
    # )
    

    # send customer location
    # await _async_wa_client.send_location(
    #     to=recipient,
    #     latitude=delivery_detail.customer_lat,
    #     longitude=delivery_detail.customer_lon,
    #     name=f"{delivery_detail.customer_name} Drop Off",
    #     address=delivery_detail.customer_address,
    # )

    pickup_time = (datetime.now() + timedelta(minutes=25)).strftime("%I:%M %p")
   
    wa_text = f"""
    Pickup time - *{pickup_time}*

Pickup location - *{delivery_detail.rest_name}*
{delivery_detail.rest_address}

Drop off location - *{delivery_detail.customer_name}*
{delivery_detail.customer_address}

Order number - *{delivery_detail.order_number}*
    """
    await _async_wa_client.send_message(
        to=recipient,
        # reply_to_message_id=msg.id,
        header=f'1.2 Miles, £3.5, @{pickup_time}',
        text=wa_text,
        footer='⚡Ordelo',
        buttons=[
            Button(title='Accept', callback_data=json.dumps(accept_pl)),
            Button(title='Decline', callback_data=json.dumps(decline_pl)),
        ]
    )


# %% Define paths
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
async def delivery_hook_root():
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
