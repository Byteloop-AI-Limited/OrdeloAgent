# %%
from config import waba_business_settings, waba_cat_settings, _async_wa_client, _sync_wa_client
from typing import List, Optional
from pywa.types import Template as Temp, Button, ButtonUrl
from pywa_async import WhatsApp
import asyncio
from pywa.types import ProductsSection
import json
from config import logger
import psycopg
from psycopg_pool import ConnectionPool
import base64
from datetime import datetime, timedelta
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from utils_common.db_utils.sbase_rest_ops import sbase_update, sbase_get, sbase_sync_update, sbase_sync_get


# %% Send Delivery Dispatch
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



# %% Send Delivery Dispatch Response
def process_dispatch_response_from_rider_sync(
    pool_sync: ConnectionPool,
    rider_id: str,
    callback_data: dict,
    _sync_wa_client: WhatsApp = _sync_wa_client
):
    """
    Processes the rider's response to a delivery dispatch in a synchronous context.

    Depending on whether the rider accepted or declined the job, it updates the
    delivery dispatch and delivery detail records in the database accordingly.

    Args:
        pool_sync (ConnectionPool): A synchronous connection pool for database operations.
        recipient (str): The phone number of the rider.
        callback_data (dict): The callback data containing the dispatch ID, order number, and rider response.
        _sync_wa_client (WhatsApp, optional): The WhatsApp client for sending messages. Defaults to _sync_wa_client.

    """
    dispatch_id = callback_data['dispatch_id']
    order_number = callback_data['order_number']
    rider_response = callback_data['status']
    
    with pool_sync.connection() as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if rider_response == 'accepted':
                # Check current status
                cur.execute(
                    "SELECT * FROM delivery_detail WHERE order_number = %s",
                    (order_number,)
                )
                _detail = cur.fetchone()

                if _detail and _detail['status'] == 'assigned':
                    # Job already assigned, update dtts
                    cur.execute(
                        """
                        UPDATE delivery_dispatch 
                        SET status_update_dtts = %s 
                        WHERE dispatch_id = %s
                        """,
                        (datetime.now().isoformat(), dispatch_id)
                    )
                    # Job already assigned
                    _sync_wa_client.send_message(
                        to=rider_id,
                        text='Sorry, This job has already been assigned'
                    )
                    return_value = "job already assigned"
                else:
                        # Update dispatch status
                        cur.execute(
                            """
                            UPDATE delivery_dispatch 
                            SET status = 'assigned', status_update_dtts = %s 
                            WHERE dispatch_id = %s
                            """,
                            (datetime.now().isoformat(), dispatch_id)
                        )
                        
                        # Update delivery detail
                        cur.execute(
                            """
                            UPDATE delivery_detail 
                            SET status = 'assigned', dispatch_id = %s, rider_id = %s 
                            WHERE order_number = %s
                            """,
                            (dispatch_id, rider_id, order_number)
                        )

                        # Update delivery_inflight
                        cur.execute(
                            """
                            INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
                            VALUES (%s, %s, %s, (SELECT customer_id FROM delivery_detail WHERE order_number = %s LIMIT 1))
                            """,
                            (dispatch_id, order_number, rider_id, order_number)
                        )

                        _sync_wa_client.send_message(
                            to=rider_id,
                            text='Thank you for accepting the job!'
                        )
                        return_value = _detail
            else:
                cur.execute(
                    """
                    UPDATE delivery_dispatch 
                    SET status = 'declined', status_update_dtts = %s 
                    WHERE dispatch_id = %s
                    """,
                    (datetime.now().isoformat(), dispatch_id)
                )
                return_value = "job declined"
        conn.commit()
        return return_value
        # conn.commit()



# %% live location on map 
async def get_live_location_map_url(order_number: str):

    current_location=f"https://maps.google.com/?q=Order('{order_number}')@51.354126,0.099301"

    return {"current_location": current_location}

# %% Non Driver Senders

async def send_request_payment_link(
    recipient: str,
    user_name: str,
    stripe_link: str,
    order_id: str,
    _async_wa_client: WhatsApp = _async_wa_client,
) -> Optional[dict]:
    
    await _async_wa_client.send_template(
        to=recipient,
        template=Temp(
            name="request_payment",
            language=Temp.Language.ENGLISH_UK,
            body=[
                Temp.TextValue(value=user_name),
                Temp.TextValue(value=order_id),
            ],
            buttons=[
                Temp.UrlButtonValue(value=stripe_link),
            ],
        ),
    )

async def send_reservation_link(
    recipient: str,
    user_name: str,
    reservation_id: str,
    _async_wa_client: WhatsApp = _async_wa_client,
) -> Optional[dict]:
    """
    Sends a WhatsApp template message with a reservation link.

    Args:
        _async_wa_client: An instance of the AsyncWhatsAppClient.
        recipient: The phone number of the recipient.
        user_name: The name of the user, to be included in the message.
        reservation_id: The reservation ID, used to generate the link.

    Returns:
        The result of the send_template call (likely a dictionary), or None on error.
    """
    try:
        reservation_link = await _async_wa_client.send_template(
            to=recipient,
            template=Temp(
                name='send_reservation_link',
                language=Temp.Language.ENGLISH_UK,
                body=[
                    Temp.TextValue(value=f"{user_name}"),
                    Temp.TextValue(value=f"{reservation_id}"),
                ],
                buttons=[
                    Temp.UrlButtonValue(value=f"{reservation_id}"),
                ]
                )
            )
        return reservation_link
    except Exception as e:
        print(f"Error sending reservation link: {e}")
        return None


# %% Send catalog
async def send_catalog(
    recipient: str,
    _async_wa_client: WhatsApp = _async_wa_client,
) -> Optional[dict]:
    await _async_wa_client.send_message(
                to=recipient,
                text=waba_cat_settings.cat_link,
                preview_url=True,
            )
    return


# %% Send order reciept after payment 
async def send_order_reciept_wa(
    recipient: str,
    receipt: List[str],
    _async_wa_client: WhatsApp = _async_wa_client,
) -> Optional[dict]:
    await _async_wa_client.send_template(
        to=recipient,
        template=Temp(
            name='payment_reciept_elai',
            language=Temp.Language.ENGLISH_UK,
            body=[
                Temp.TextValue(value=receipt[0]),
                Temp.TextValue(value=receipt[1]),
                Temp.TextValue(value=receipt[2]),
                Temp.TextValue(value=receipt[3]),
            ],
        )  
    )
    return


async def send_delayed_text(recipient: str, text: str, wait_time: int=3):
    """
    Sends a text message to a recipient with a specified delay.

    Args:
        recipient: The phone number of the recipient.
        text: The message text to be sent.
        wait_time: The time in seconds to wait before sending the message (default is 3 seconds).

    """
    await asyncio.sleep(wait_time)
    await _async_wa_client.send_text(to=recipient, text=text)


# %% Send product sections
async def send_product_sections(
    recipient: str, 
    food_item_query: str, 
    product_sections: List[ProductsSection], 
    _async_wa_client: WhatsApp = _async_wa_client
) -> None:
    """
    Sends product sections via WhatsApp using the catalog.

    Args:
        recipient: The phone number of the recipient.
        food_item_query: The query used to generate product sections.
        product_sections: List of product sections to send.
        _async_wa_client: An instance of the AsyncWhatsApp client.
    """
    await _async_wa_client.send_products(
        to=recipient,
        catalog_id=waba_cat_settings.cat_id,
        title=f"`{food_item_query}`",
        body="matching or related items",
        product_sections=product_sections[:30]
    )
    

# %% TEST
"""
# %%
recipient='447448440754'
user_name='10gan'
await send_driver_start_job_link(recipient=recipient)

# %%
"""