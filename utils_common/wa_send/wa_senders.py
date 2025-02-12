# %%
from config import waba_business_settings, waba_cat_settings, _async_wa_client
from typing import List, Optional
from pywa.types import Template as Temp, Button, ButtonUrl
from pywa_async import WhatsApp
import asyncio
from pywa.types import ProductsSection
import json
import base64
from datetime import datetime, timedelta
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from utils_common.db_utils.sbase_rest_ops import sbase_update, sbase_get

# %%


# %% Send Delivery Dispatch
async def wa_send_delivery_dispatch(
    recipient: str,
    delivery_detail: DeliveryDetail,
    dispatch_id: int,
    _async_wa_client: WhatsApp = _async_wa_client,
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
    await _async_wa_client.send_location(
        to=recipient,
        latitude=delivery_detail.rest_lat,
        longitude=delivery_detail.rest_lon,
        name= f"{delivery_detail.rest_name} Pick Up",
        address= delivery_detail.rest_address
    )

    # send customer location
    await _async_wa_client.send_location(
        to=recipient,
        latitude=delivery_detail.customer_lat,
        longitude=delivery_detail.customer_lon,
        name=f"{delivery_detail.customer_name} Drop Off",
        address=delivery_detail.customer_address,
    )

    pickup_time = (datetime.now() + timedelta(minutes=25)).strftime("%I:%M %p")
    # print(delivery_detail.map_url)

    # msg =await _async_wa_client.send_message(
    #     to=recipient,
    #     header='Job details: 1.2 Miles £3.5',
    #     text=f'Pickup time - {pickup_time}',
    #     reply_to_message_id=None,
    #     footer='⚡Ordelo',
    #     buttons=ButtonUrl(title='View on Map', url=delivery_detail.google_maps_url),
    # )
   
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
async def wa_send_delivery_dispatch_response(
    recipient: str,
    callback_data: dict,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    _dispatch_id = callback_data['dispatch_id']
    _order_number = callback_data['order_number']

    if callback_data['status'] == 'declined':
        await sbase_update(
            update_fields={"status": "declined"},
            table_name="delivery_dispatch",
            dispatch_id=_dispatch_id
        )

    elif callback_data['status'] == 'accepted':
        delivery_dispatch = await sbase_get("delivery_dispatch", dispatch_id=_dispatch_id)

        if delivery_dispatch[0]['status'] == 'accepted':
            await _async_wa_client.send_message(
                to=recipient,
                text='Sorry, This job has already been assigned'
            )
        else:
            # No one has accepted the job yet, so update the status
            await sbase_update(
                update_fields={"status": "accepted"},
                table_name="delivery_dispatch",
                dispatch_id=_dispatch_id
            )
            await sbase_update(
                update_fields={"status": "accepted", "dispatch_id": _dispatch_id},
                table_name="delivery_detail",
                order_number=_order_number
            )


# %% Send Start Live Tracking Link

async def send_start_live_tracking_link(
    recipient: str,
    delivery_detail: DeliveryDetail,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    waypoints = [
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "restaurant",
            "desc": "restaurant",
            "rad": 10,
            "lat": delivery_detail.rest_lat,
            "lon": delivery_detail.rest_lon
        },
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "customer",
            "desc": "customer",
            "rad": 10,
            "lat": delivery_detail.customer_lat,
            "lon": delivery_detail.customer_lon
        },
        ]

    start_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": True,
        "usePassword" : False,
        "monitoring": 2,
        "username": "447448440754",
        "deviceId": "447448440754-order123",
        "password": "",
        "url": "https://live-track.byteloop.ai/pub",
        "locatorDisplacement": 10,
        "locatorInterval" : 10,
        "waypoints": waypoints
    }
    # Encode config as href
    start_href = generate_config_href(start_job_config)

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