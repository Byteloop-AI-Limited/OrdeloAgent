# %%
from config import waba_business_settings, waba_cat_settings
from typing import List, Optional
from pywa.types import Template as Temp
from pywa_async import WhatsApp
import asyncio
from pywa.types import ProductsSection, ButtonUrl
import json
import base64
from datetime import datetime

_async_wa_client = waba_business_settings.create_wa()

# %%
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"



# %% Driver Senders
async def send_start_live_tracking_link(
    recipient: str,
    _async_wa_client: WhatsApp = _async_wa_client,
):
    waypoints = [
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "restaurant",
            "desc": "restaurant",
            "rad": 10,
            "lat": 51.354107,
            "lon": 0.095921
        },
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "customer",
            "desc": "customer",
            "rad": 10,
            "lat": 51.37367242361126,
            "lon": 0.09653313354081415
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
        text=f"Start Job",
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