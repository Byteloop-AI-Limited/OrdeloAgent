"""
Send delivery instructions via WhatsApp for a given dispatch_id.
    . Uses pg_settings and _async_wa_client from config
    . send_delivery_instructions(dispatch_id):
        - Fetches delivery_dispatch and delivery_summary records
        - Calculates pickup time
        - Sends restaurant and customer locations via WhatsApp
    . All logic is wrapped in an async function for reuse
"""

# %%
import datetime
from datetime import timedelta
from config import pg_settings, _async_wa_client
from pywa.types import ButtonUrl
from pywa.types import Button


async def send_delivery_instructions(dispatch_id: int):
    """
    Sends delivery instructions (pickup and drop-off locations) via WhatsApp for a given dispatch_id.
    """
    client = pg_settings.client

    dispatch = (
        client.table("delivery_dispatch")
        .select("*")
        .eq("dispatch_id", dispatch_id)
        .limit(1)
        .execute()
        .data[0]
    )
    order_number = dispatch["order_number"]

    summary = (
        client.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )

    recipient = "447448440754"
    delivery_summary_dtts = datetime.datetime.fromisoformat(summary["dtts"])
    pickup_time = (delivery_summary_dtts + timedelta(minutes=25)).strftime("%I:%M %p")

    body_text = f"""

  ⏰ Pickup Time - *@{pickup_time}*
  💰 Earning - *£{dispatch["rider_payout"]}*
  🛣️ Distance - *{dispatch["distance"]} miles*

🚀 Get started with the delivery by cliking the below link

🔑 2-digit *Restaurant* confirmation code after the delivery is completed!

🔑 2-digit *Customer* confirmation code after the delivery is completed!

👨‍💻 Please let me know if you have any questions during the delivery process.
    """
    start_live_tracking_url = "https://example.com"
    delivery_instructions_msg = await _async_wa_client.send_message(
        to=recipient,
        header=f"🌟 {summary['order_number']} 🌟",
        text=body_text,
        reply_to_message_id=None,
        buttons=[
            # ButtonUrl(title="Start live tracking", url=start_live_tracking_url),
            Button(title="Get Pickup Location", callback_data="pickup_location"),
            Button(title="Get Dropoff Location", callback_data="dropoff_location"),
        ],
    )

    await _async_wa_client.send_location(
        to=recipient,
        latitude=summary["rest_lat"],
        longitude=summary["rest_lon"],
        name=f"{summary['rest_name']} - Pick Up",
        address=summary["rest_address"],
        reply_to_message_id=delivery_instructions_msg.id,
    )

    await _async_wa_client.send_location(
        to=recipient,
        latitude=summary["customer_lat"],
        longitude=summary["customer_lon"],
        name=f"{summary['customer_name']} - Drop Off",
        address=summary["customer_address"],
        reply_to_message_id=delivery_instructions_msg.id,
    )


# %%
await send_delivery_instructions(dispatch_id=2329)
