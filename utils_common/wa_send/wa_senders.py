# %%
from config import waba_business_settings, waba_cat_settings, _async_wa_client, _sync_wa_client
from typing import List, Optional
from pywa.types import Template as Temp, Button, ButtonUrl
from pywa_async import WhatsApp
import asyncio
from pywa.types import ProductsSection
import json
from config import logger
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
    recipient: str,
    callback_data: dict,
    _sync_wa_client: WhatsApp = _sync_wa_client
):
    """
    Process rider's response to a delivery dispatch (synchronous version).
    
    This function executes database operations in a synchronous context.
    
    Args:
        recipient: The phone number of the recipient.
        callback_data: The callback data containing the dispatch ID and order number.
        _async_wa_client: An instance of the WhatsApp client.
    
    Returns:
        None
    """
    _dispatch_id = callback_data['dispatch_id']
    _order_number = callback_data['order_number']
    rider_response = callback_data['status']
    
    if rider_response == 'declined':
        sbase_sync_update(
            update_fields={"status": "declined", "status_update_dtts": datetime.now().isoformat()},
            table_name="delivery_dispatch",
            dispatch_id=_dispatch_id
        )

    elif rider_response == 'accepted':
        # get latest dispatch details
        _detail = sbase_sync_get("delivery_detail", order_number=_order_number)
        status = _detail[0]['status']

        if status == 'assigned':
            # Job is already accepted
            _sync_wa_client.send_message(
                to=recipient,
                text='Sorry, This job has already been assigned'
            )
        else:
            # No one has accepted the job yet, so update the status
            # Update dispatch
            sbase_sync_update(
                update_fields={"status": "assigned", "status_update_dtts": datetime.now().isoformat()},
                table_name="delivery_dispatch",
                dispatch_id=_dispatch_id
            )

            # Update detail with dispatch_id
            sbase_sync_update(
                update_fields={"status": "assigned", "dispatch_id": _dispatch_id, "rider_id": recipient},
                table_name="delivery_detail",
                order_number=_order_number
            )


async def process_dispatch_response_from_rider(
    recipient: str,
    callback_data: dict,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Process rider's response to a delivery dispatch.
    
    This function executes database operations in an async context.
    
    Args:
        recipient: The phone number of the recipient.
        callback_data: The callback data containing the dispatch ID and order number.
        _async_wa_client: An instance of the AsyncWhatsApp client.
    
    Returns:
        None
    """
    _dispatch_id = callback_data['dispatch_id']
    _order_number = callback_data['order_number']
    rider_response = callback_data['status']
    
    if rider_response == 'declined':
        await sbase_update(
            update_fields={"status": "declined", "status_update_dtts": datetime.now().isoformat()},
            table_name="delivery_dispatch",
            dispatch_id=_dispatch_id
        )

    elif rider_response == 'accepted':
        # get latest dispatch details
        _detail = await sbase_get("delivery_detail", order_number=_order_number)
        status = _detail[0]['status']

        if status == 'assigned':
            # Job is already accepted
            await _async_wa_client.send_message(
                to=recipient,
                text='Sorry, This job has already been assigned'
            )
        else:
            # No one has accepted the job yet, so update the status
            # Update dispatch
            await sbase_update(
                update_fields={"status": "assigned", "status_update_dtts": datetime.now().isoformat()},
                table_name="delivery_dispatch",
                dispatch_id=_dispatch_id
            )

            # Update detail with dispatch_id
            await sbase_update(
                update_fields={"status": "assigned", "dispatch_id": _dispatch_id, "rider_id": recipient},
                table_name="delivery_detail",
                order_number=_order_number
            )


# %% Send Start Live Tracking Link
# fair and consistent
async def send_start_live_tracking_link(
    recipient: str,
    start_href: str,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    _text="""
    Thank you for accepting the job! Please use the live tracking link below to start tracking your delivery.
    Remember to provide the 2-digit confirmation code after the delivery is completed!
    Please let me know if you have any questions during the delivery process. 
    """
    await _async_wa_client.send_message(
        to=recipient,
        text=f"Start Live Tracking",
        reply_to_message_id=None,
        buttons=ButtonUrl(title="Click Here", url=start_href)
    )
    return True

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