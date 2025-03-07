from fastapi import APIRouter, Request, Depends
from ordelo_datamodels.delivery_pymodels import DeliveryDetail

from config import logger, _async_wa_client, pg_settings
from pywa.types import Button
from pywa_async import WhatsApp
from datetime import datetime, timedelta
import json
from psycopg_pool import AsyncConnectionPool
from ordelo.agent_app_handlers import init_ordelo_graph
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
import asyncio

# %%


# %% Define Dependancies and routes
async def get_payload(request: Request):
    return await request.json()

async def get_pool(request: Request):
    # Get pool from the main app
    return request.app.state.pool

async def get_graph(request: Request):
    # Get pool from the main app
    return request.app.state.graph

client = pg_settings.client

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
        "status": "accepted",
        "rider_id": recipient
    }

    decline_pl = {
        "command": "/dispatchResponse",
        "order_number": order_number,
        "dispatch_id": dispatch_id,
        "status": "declined",
        "rider_id": recipient
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
async def delivery_dispatch_hook(payload: dict = Depends(get_payload)):
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

# %% Delivery Inflight Graph Init
@router.post("/delivery-inflight-graph-init",
    summary="Initialize Delivery Inflight Graph",
    description="""
    Processes a new delivery inflight record and initializes the delivery tracking graph.
    
    This endpoint:
    1. Receives delivery inflight and detail information
    2. Validates the payload contains required information
    3. Initializes the delivery tracking graph for the inflight delivery
    """,
    response_description="Status of the graph initialization operation and the processed data",
    responses={
        200: {
            "description": "Successfully initialized delivery tracking graph",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "delivery_inflight": [{"dispatch_id": "123", "rider_id": "456", "order_number": "789"}],
                            "delivery_detail": [{"order_number": "789", "customer_name": "John Doe"}]
                        }
                    }
                }
            }
        }
    }
)
async def delivery_inflight_graph_init_hook(
    payload: dict = Depends(get_payload),
    graph = Depends(get_graph),
    pool: AsyncConnectionPool = Depends(get_pool)
):
    """
    On insert into delivery_inflight table, trigger delivery inflight graph initialization webhook.

    This endpoint processes a delivery inflight record by extracting 
    rider ID, dispatch ID, order number, and delivery details from the request payload.
    It then initializes the delivery tracking graph for this inflight delivery.

    Args:
        request (Request): The HTTP request object containing JSON payload.

    Returns:
        dict: A dictionary with the status of the operation and the original 
              payload data.
    """
    # Validate payload   
    if 'delivery_detail' not in payload or len(payload['delivery_detail']) == 0:
        logger.error("No delivery_detail found: from inflight hook")
        return {"status": "error", "data": payload}

    # Extract data from payload
    delivery_detail = DeliveryDetail(**payload['delivery_detail'][0])

    # Create as background task as the db webhook on inflight waits and errors out
    asyncio.create_task(init_ordelo_graph(graph, pool, delivery_detail))

    return {"status": "success"}

# %% Notify missed dispatches
@router.post("/notify-missed-dispatches",
    summary="Notify Missed Dispatches",
    description="""
    Notifies riders about missed dispatches.
    
    This endpoint:
    1. Receives order_number and a list of rider IDs
    2. Sends a notification to each rider (logger.info)
    3. Uses sbase_update(table='delivery_dispatch', {"status": "missed"}, order_number=order_number)
    """,
    response_description="Status of the notification operation and the processed data",
    responses={
        200: {
            "description": "Successfully notified about missed dispatches",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "data": {
                            "order_numbers": ["ORD123", "ORD456"],
                            "updated_dispatch_count": 5
                        }
                    }
                }
            }
        }
    }
)
async def notify_missed_dispatches_hook(payload: dict = Depends(get_payload)):
    """
    Process missed dispatches notification.
    
    This endpoint receives information about dispatches that have timed out
    and updates their status to 'missed' in the database. It also logs
    notifications that would be sent to riders.
    
    Args:
        request (Request): The HTTP request object containing JSON payload.
        
    Returns:
        dict: A dictionary with the status of the operation and summary data.
    """
    # from ordelo.sbase import sbase_update
    
    # Handle empty or missing missed_dispatches
    if 'missed_dispatches' not in payload or not payload['missed_dispatches']:
        logger.info("No missed_dispatches data found in payload, nothing to process")
        return {"status": "success", "message": "No missed dispatches to process", "data": {"order_numbers": [], "updated_dispatch_count": 0}}
    
    order_numbers = []
    
    # Process each order with missed dispatches
    for missed_dispatch in payload['missed_dispatches']:
        logger.info(f"notify_missed_dispatches_hook received: {missed_dispatch}")

        order_number = missed_dispatch['order_number']
        order_numbers.append(order_number)
        
        dispatches_to_be_updated_as_missed = []
        
        # Log notification for each rider
        for dispatch in missed_dispatch['dispatches']:
            rider_id = dispatch['rider_id']
            dispatch_id = dispatch['dispatch_id']
            dispatches_to_be_updated_as_missed.append(dispatch_id)

            _text = f"""
            Sorry, the order was picked up by another rider. Order number: *{order_number}*
            """

            # send notification to rider
            await _async_wa_client.send_message(
                to=rider_id,
                text=_text
            )
        
        # Mark dispatches as missed, they will not be pickup by notify_missed_dispatches sql function again
        response = client.table("delivery_dispatch")\
            .update({"status": "missed"})\
            .in_("dispatch_id", dispatches_to_be_updated_as_missed)\
            .execute()

        logger.success(f"Marked dispatches as missed for order {response}")
        # Update dispatch status to 'missed'
        # try:
        #     # Update all unassigned dispatches for this order to 'missed'
        #     result = await sbase_update(
        #         table='delivery_dispatch', 
        #         values={"status": "missed", "status_update_dtts": "CURRENT_TIMESTAMP"}, 
        #         where={"order_number": order_number, "status": "unassigned"}
        #     )
            
        #     if result and 'affected_rows' in result:
        #         updated_count += result['affected_rows']
        #         logger.info(f"Updated {result['affected_rows']} dispatch records to 'missed' for order {order_number}")
        #     else:
        #         logger.warning(f"No dispatch records updated for order {order_number}")
                
        # except Exception as e:
        #     logger.error(f"Error updating dispatch status for order {order_number}: {str(e)}")
    
    return {"status": "success"}