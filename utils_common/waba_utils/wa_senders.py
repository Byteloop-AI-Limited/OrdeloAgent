"""
WhatsApp messaging utilities for order management and address confirmation flows
    . Implements WhatsApp communication for delivery and order management
    . Defines reusable models for button callbacks with immutable properties
    . Supports extra fields in callback data (extra="allow") for flexibility
    . Sends admin notifications for order and delivery status updates
    . Provides interactive address confirmation flows with buttons
    . Implements postcode search/update flows via WhatsApp Flow API
    . Uses FlowButton for complex user interactions and form submissions
  Functions/Classes:
    . CallbackButtonData - Pydantic model for WhatsApp button callback data
    . admin_delivery_complete_notification - Notifies admins about completed deliveries
    . admin_order_reciept - Sends order receipts to admins with delivery details
    . confirm_delivery_address_wa - Sends address confirmation requests to customers
    . send_postcode_search_flow - Initiates postcode search flow via WhatsApp
"""

# %%
from config import _async_wa_client, project_settings
from pywa.types import FlowButton
from pywa.types.flows import FlowActionType
from pydantic import BaseModel
from pywa.types import Button
import uuid
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.delivery_pymodels import DeliverySummary
from utils_common.order_management.food_order_reciept import (
    build_wa_order_reciept_for_rest,
)

# from utils_common.vec_ops.vec_search import get_product_sections
from pywa_async import WhatsApp
from config import waba_cat_settings
from typing import Optional
from config.params import REST_MASTER
from datetime import timedelta
import pytz
from pywa import WhatsApp
from pywa.types import (
    Message,
)
from pywa.types.templates import *

uk_tz = pytz.timezone("Europe/London")


# %% reusable button callback model
class CallbackButtonData(BaseModel):
    model_config = {"frozen": True, "extra": "allow"}
    action: str
    recipient: str
    ai_msg: str
    human_msg: str


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
    delivery_summary: DeliverySummary, delivery_detail: dict, rider_master: dict
):
    order_number = delivery_summary.order_number
    order_id = "-".join(order_number.split("-")[1:])

    food_order = FoodOrder.from_order_id(order_id)
    rest_header, rest_text = build_wa_order_reciept_for_rest(food_order=food_order)

    # Construct delivery instructions
    # convert dtts to UK local time (handles BST/GMT automatically)
    delivery_summary_dtts = delivery_summary.dtts.astimezone(uk_tz)
    pickup_time = (delivery_summary_dtts + timedelta(minutes=25)).strftime("%I:%M %p")
    delivery_instructions = f"""
Delivery Details:
  ⏰ Pickup Time - *@{pickup_time}*
  💰 Rider - *{rider_master["rider_name"]} - {delivery_detail["rider_id"]}*
  🛣️ Confirmation Code - *{delivery_summary.rest_confirmation_code}*
  🏠 Customer - *{delivery_summary.customer_address}* - *{delivery_summary.customer_id}*
    Live Location (once order picked up): 
    {project_settings.ordelo_url}/location-hooks/live-location-map/{delivery_summary.order_number}
    """
    # Send notifications to restaurant and customer; ToDo - need to add callback to notifications.
    temp_admins = ["447448440754"]
    for admin in REST_MASTER.get_admins():
        # for admin in temp_admins:
        food_ready_y = CallbackButtonData(
            action="/AdminCollectionReady",
            recipient=admin,
            ai_msg=rest_header,
            human_msg="food ready for collection",
            rider_id=rider_master["rider_id"],
            order_id=order_id,
        )
        await _async_wa_client.send_message(
            to=admin,
            header=rest_header,
            text=rest_text + "\n" + delivery_instructions,
            reply_to_message_id=None,
            buttons=[
                Button(title="Ready", callback_data=food_ready_y.model_dump_json())
            ],
        )
    return


# %% Admin notification
async def admin_order_reciept(
    delivery_summary: DeliverySummary, delivery_detail: dict, rider_master: dict
):
    order_number = delivery_summary.order_number
    order_id = "-".join(order_number.split("-")[1:])

    food_order = FoodOrder.from_order_id(order_id)
    rest_header, rest_text = build_wa_order_reciept_for_rest(food_order=food_order)

    # Construct delivery instructions
    # convert dtts to UK local time (handles BST/GMT automatically)
    delivery_summary_dtts = delivery_summary.dtts.astimezone(uk_tz)
    pickup_time = (delivery_summary_dtts + timedelta(minutes=25)).strftime("%I:%M %p")
    delivery_instructions = f"""
Delivery Details:
  ⏰ Pickup Time - *@{pickup_time}*
  💰 Rider - *{rider_master["rider_name"]} - {delivery_detail["rider_id"]}*
  🛣️ Confirmation Code - *{delivery_summary.rest_confirmation_code}*
  🏠 Customer - *{delivery_summary.customer_address}* - *{delivery_summary.customer_id}*
    Live Location (once order picked up): 
    {project_settings.ordelo_url}/location-hooks/live-location-map/{delivery_summary.order_number}
    """
    # Send notifications to restaurant and customer; ToDo - need to add callback to notifications.
    temp_admins = ["447448440754"]
    for admin in REST_MASTER.get_admins():
        # for admin in temp_admins:
        food_ready_y = CallbackButtonData(
            action="/AdminCollectionReady",
            recipient=admin,
            ai_msg=rest_header,
            human_msg="food ready for collection",
            rider_id=rider_master["rider_id"],
            order_id=order_id,
        )
        await _async_wa_client.send_message(
            to=admin,
            header=rest_header,
            text=rest_text + "\n" + delivery_instructions,
            reply_to_message_id=None,
            buttons=[
                Button(title="Ready", callback_data=food_ready_y.model_dump_json())
            ],
        )
    return


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


# %%
# waba_cat_settings.cat_link


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

    # Getting invalid catalog_id error, tried with
    # product_sections = get_product_sections()
    # await _async_wa_client.send_products(
    #     to=recipient,
    #     catalog_id=waba_cat_settings.cat_id,
    #     title="Catalog",
    #     body="Here is the catalog",
    #     product_sections=product_sections[:30],
    # )

    return


# %%
"""
# %%
await send_postcode_search_flow(recipient="447448440754", postcode_init="BR6 6DN")
# %%
"""
# %%
