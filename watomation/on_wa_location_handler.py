"""Priority PyWa handler for native WhatsApp current-location responses."""

from __future__ import annotations

from datetime import datetime, timezone

from pywa.types import Message
from pywa_async import WhatsApp

from config import logger, pg_settings
from ordelo.wa_location import WaLocation
from ordelo_datamodels.wa_location_pymodels import WhatsAppLocationReceipt
from utils_common.thread_management import ThreadHandler


def _observed_at(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 1_000_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return datetime.now(timezone.utc)


async def handle_wa_location_message(wa: WhatsApp, msg: Message) -> None:
    """Consume location messages before the generic rider graph handler."""

    location = getattr(msg, "location", None)
    if location is None:
        return
    recipient = msg.from_user.wa_id
    if getattr(location, "current_location", False) is not True:
        await wa.send_message(
            to=recipient,
            text="Please use WhatsApp's Share current location option for this request.",
            reply_to_message_id=msg.id,
        )
        return

    reply_to = getattr(msg, "reply_to_message", None)
    try:
        correlated = await WaLocation(wa_client=wa).receive_whatsapp_location(
            WhatsAppLocationReceipt(
                rider_id=recipient,
                latitude=location.latitude,
                longitude=location.longitude,
                observed_at=_observed_at(getattr(msg, "timestamp", None)),
                inbound_message_id=msg.id,
                reply_to_message_id=getattr(reply_to, "id", None),
            )
        )
        if correlated:
            pool = await pg_settings.get_pool()
            if await ThreadHandler(pool).get_active_thread(recipient):
                from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg

                await run_rider_agent_w_custom_msg(
                    recipient=recipient,
                    system_msg=(
                        "Rider shared their current location and it has been "
                        "sent to the requester. Acknowledge briefly in one line."
                    ),
                )
    except Exception as exc:
        # The message is intentionally consumed: sending it to the rider graph
        # would create an unrelated conversational response to coordinates.
        logger.exception(
            "WaLocation inbound processing failed for rider={} error={}",
            recipient,
            type(exc).__name__,
        )
