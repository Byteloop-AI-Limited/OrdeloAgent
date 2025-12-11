"""
WhatsApp messaging utilities for order management and address confirmation flows
    . Implements WhatsApp communication for delivery and order management
    . Defines reusable models for button callbacks with immutable properties
    . Supports extra fields in callback data (extra="allow") for flexibility
    . Sends admin notifications for order and delivery status updates
    . Provides interactive address confirmation flows with buttons
    . Implements postcode search/update flows via WhatsApp Flow API
    . Uses FlowButton for complex user interactions and form submissions
    . Sends catalog products and sections
    . Sends payment and reservation links
  Functions/Classes:
    . CallbackButtonData - Pydantic model for WhatsApp button callback data
    . admin_delivery_driver_nearby - Notifies admin driver is nearby
    . admin_delivery_complete_notification - Notifies admins about completed deliveries
    . admin_order_reciept - Sends order receipts to admins with delivery details
    . confirm_delivery_address_wa - Sends address confirmation requests to customers
    . send_postcode_search_flow - Initiates postcode search flow via WhatsApp
    . send_request_payment_link - Sends payment link to customer
    . send_reservation_link - Sends reservation link to customer
    . send_catalog - Sends catalog link to customer
    . send_order_reciept_wa - Sends customer receipt
    . send_delayed_text - Sends text with delay
    . send_product_sections - Sends product sections from catalog
"""

# %%
from config import (
    _async_wa_client,
    project_settings,
    waba_business_settings,
    waba_cat_settings,
)
from config.params import get_restaurant_admins, get_restaurant_base_url_async
from pywa.types import FlowButton, Button, Template as Temp, ProductsSection
from pywa.types.flows import FlowActionType
from pydantic import BaseModel
import uuid

# from utils_common.order_management.food_order_pymodel import FoodOrder
# from utils_common.order_management.delivery_pymodels import DeliverySummary
# from utils_common.order_management.food_order_reciept import (
#     build_wa_order_reciept_for_rest,
# )
from pywa_async import WhatsApp
from typing import Optional, List
from datetime import timedelta
import pytz
import asyncio
from utils_common.order_management.delivery_pymodels import (
    DeliverySummary,
    DeliveryDetail,
)
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.food_order_reciept import (
    build_wa_order_reciept_for_rest,
)


# from config.params import REST_MASTER
REST_MASTER = "dummy"


uk_tz = pytz.timezone("Europe/London")


# %% reusable button callback model

# class CallbackButtonData(BaseModel):
#     model_config = {"frozen": True, "extra": "allow"}
#     action: str
#     recipient: Optional[str] = None
#     ai_msg: Optional[str] = None
#     human_msg: Optional[str] = None


class CallbackButtonData(BaseModel):
    model_config = {"frozen": True, "extra": "allow"}
    action: str


# %%


# order_time is not str, its int and in epoch format
async def send_restaurant_pickup_time(
    recipient: str,
    header: str,
    text: str,
    order_number: str,
    order_time_epoch: int,
    intervals_mins: List[int] = None,
):
    # Parse order_time string to datetime
    from datetime import datetime

    # Use default intervals if none provided
    if intervals_mins is None:
        intervals_mins = [5, 15, 25]

    # Parse the order_time (assuming ISO format or similar)
    order_dt = datetime.fromtimestamp(order_time_epoch)

    # Calculate times and create buttons dynamically
    buttons = []
    for interval in intervals_mins:
        # Calculate the time for this interval
        pickup_time = order_dt + timedelta(minutes=interval)

        # Format for button title (e.g., "1:35 PM")
        time_display = pickup_time.strftime("%-I:%M %p")

        # Format for callback response (ISO string representation)
        time_str = pickup_time.isoformat()

        # Create callback data
        callback_data = CallbackButtonData(
            action="/PickupTime",
            pickup_time=time_str,
            order_number=order_number,
        )

        # Add button
        buttons.append(
            Button(
                title=time_display,
                callback_data=callback_data.model_dump_json(),
            )
        )

    await _async_wa_client.send_message(
        to=recipient,
        header=header,
        text=text,
        preview_url=False,
        buttons=buttons,
    )


# %%

# await restaurant_pickup_time(
#     recipient="447448440754",
#     header="Header",
#     text="Text",
#     order_number="REST-12345",
#     order_time="2023-01-01T12:00:00Z",
#     intervals_mins=[5, 10, 25],
# )


# %% Admin Delivery complete notification
async def admin_delivery_driver_nearby(
    order_number: str,
    rest_confirmation_code: str,
):
    # Todo: include the rider name in the notification
    # Send notifications to restaurant and customer; ToDo - need to add callback to notifications.
    for admin in REST_MASTER.get_admins():
        await _async_wa_client.send_message(
            to=admin,
            # header=rest_header,
            text=f"Delivery driver is nearby for order number: {order_number} - Confirmation Code: {rest_confirmation_code}",
            reply_to_message_id=None,
        )
    return


# %% Admin Delivery complete notification
async def admin_delivery_complete_notification(
    order_number: str,
):
    # ToDo: should this be order_id ?
    # Send notifications to restaurant and customer; ToDo - need to add callback to notifications.
    for admin in REST_MASTER.get_admins():
        await _async_wa_client.send_message(
            to=admin,
            # header=rest_header,
            text=f"✅ Delivery completed for order number: {order_number}",
            reply_to_message_id=None,
        )
    return


# %% Admin notification


async def admin_order_reciept(
    delivery_summary: DeliverySummary,
    rider_master: dict,
):
    order_number = delivery_summary.order_number
    order_id = "-".join(order_number.split("-")[1:])

    food_order = FoodOrder.from_order_id(order_id)
    rest_header, rest_text = build_wa_order_reciept_for_rest(food_order=food_order)

    # Construct delivery instructions
    # convert dtts to UK local time (handles BST/GMT automatically)
    # delivery_summary_dtts = delivery_summary.dtts.astimezone(uk_tz)
    # pickup_time = (delivery_summary_dtts + timedelta(minutes=25)).strftime("%I:%M %p")
    ordelo_base_url = await get_restaurant_base_url_async(rest_ref="ORDELO")
    rest_ref = delivery_summary.rest_ref
    pickup_time = delivery_summary.pickup_time.strftime("%I:%M %p")

    delivery_instructions = f"""
Delivery Details:
  ⏰ Pickup Time - *@{pickup_time}*
  💰 Rider - *{rider_master["rider_name"]} - {rider_master["rider_id"]}*
  🛣️ Confirmation Code - *{delivery_summary.rest_confirmation_code}*
  🏠 Customer - *{delivery_summary.customer_address}* - *{delivery_summary.customer_id}*
    Live Location (once order picked up):
    {ordelo_base_url}/location-hooks/live-location-map/{delivery_summary.order_number}
    """
    # Send notifications to restaurant and customer; ToDo - need to add callback to notifications.
    # temp_admins = ["447448440754"]

    # get restaurant admins
    rest_admins = get_restaurant_admins(rest_ref=rest_ref)
    for admin in rest_admins:
        food_ready_y = CallbackButtonData(
            action="/AdminCollectionReady",
            rider_id=rider_master["rider_id"],
            restaurant_name="Elai Salisbury",
            order_id=order_id,
        )
        await _async_wa_client.send_message(
            to=admin,
            header=rest_header,
            text=rest_text + "\n" + delivery_instructions,
            reply_to_message_id=delivery_summary.restaurant_msg_id,
            buttons=[
                Button(
                    title="Ready - Notify Rider",
                    callback_data=food_ready_y.model_dump_json(),
                )
            ],
        )
    return


# %%


# %%
async def confirm_delivery_address_wa(
    recipient: str, address: dict, header: str = None
):
    house_number = address.get("house_number", "")
    street = address.get("street_name", "")
    building = address.get("building", "")
    city = address.get("city", "")
    postcode = address.get("postcode", "")

    address_str = f"""
    {house_number} {building}
{street}
{city}
{postcode}
    """.strip()

    if not header:
        header = "Confirm or Update Delivery Address"

    address_confirmation_y = CallbackButtonData(
        action="/ConfirmDeliveryAddress",
        recipient=recipient,
        ai_msg=header,
        human_msg="Yes, this is my address",
        response="Yes",
    )
    address_confirmation_n = CallbackButtonData(
        action="/ConfirmDeliveryAddress",
        recipient=recipient,
        ai_msg=header,
        human_msg="No, I want to update my delivery address",
        response="No",
    )

    await _async_wa_client.send_message(
        to=recipient,
        header=header,
        text=f"""
        {address_str}
        """,
        # footer='⚡ Powered by Ordelo',
        buttons=[
            Button(title="Yes", callback_data=address_confirmation_y.model_dump_json()),
            Button(
                title="Update", callback_data=address_confirmation_n.model_dump_json()
            ),
        ],
    )
    return


# %%
async def send_postcode_search_flow(
    recipient: str, customer_name: str = None, postcode_init: str = None
):
    await _async_wa_client.send_message(
        to=recipient,
        text="Please update your delivery address by filling the form below.",
        buttons=FlowButton(
            title="Update Address",
            flow_name="PostcodeSearchElai",
            flow_token=uuid.uuid4().hex,
            # mode=FlowStatus.DRAFT,
            flow_action_type=FlowActionType.NAVIGATE,
            flow_action_screen="START",  # The screen id to open when the user clicks the button
            flow_action_payload={
                "flow_name": "PostcodeSearchElai",
                "customer_id": recipient,
                "postcode_init": postcode_init,
            },
        ),
    )


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
                name="send_reservation_link",
                language=Temp.Language.ENGLISH_UK,
                body=[
                    Temp.TextValue(value=f"{user_name}"),
                    Temp.TextValue(value=f"{reservation_id}"),
                ],
                buttons=[
                    Temp.UrlButtonValue(value=f"{reservation_id}"),
                ],
            ),
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
            name="payment_reciept_elai",
            language=Temp.Language.ENGLISH_UK,
            body=[
                Temp.TextValue(value=receipt[0]),
                Temp.TextValue(value=receipt[1]),
                Temp.TextValue(value=receipt[2]),
                Temp.TextValue(value=receipt[3]),
            ],
        ),
    )
    return


async def send_delayed_text(recipient: str, text: str, wait_time: int = 3):
    """
    Sends a text message to a recipient with a specified delay.

    Args:
        recipient: The phone number of the recipient.
        text: The message text to be sent.
        wait_time: The time in seconds to wait before sending the message (default is 3 seconds).

    """
    await asyncio.sleep(wait_time)
    await _async_wa_client.send_text(to=recipient, text=text)


# %% send product sections
async def send_product_sections(
    recipient: str,
    food_item_query: str,
    product_sections: List[ProductsSection],
    body: str = "matching or related items",
    _async_wa_client: WhatsApp = _async_wa_client,
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
        title=f"{food_item_query}",
        body=body,
        product_sections=product_sections[:30],
    )
