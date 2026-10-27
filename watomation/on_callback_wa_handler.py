"""
WhatsApp callback button handler for delivery dispatch responses
    . Processes rider responses to delivery dispatch assignments
    . Validates callback data and updates delivery status
    . Integrates with OrdeloAgent delivery graph logic
    . Handles cases where jobs are no longer available
    . Provides feedback to riders about dispatch status
    . Checks for existing inflight deliveries to prevent conflicts
    . Allows assigned rider to decline the same inflight job pre‑pickup, forwarding to cancel flow
    . Serves as entry point into the LangGraph agent workflow
    . Processes restaurant confirmation of food preparation time
    . Restaurant Accept/Decline and pickup-time taps go through utils_common.order_management.restaurant_decision (shared with Telegram): first decision wins atomically in SQL, a losing tap is told who decided
    . Uses asyncio.create_task for long-running RPC calls to avoid timeouts
    . Guards pickup-time updates so stale or repeated button taps cannot overwrite existing pickup times
    . Supports admin pickup-time adjustment after pickup_time is set, flagging restaurant_pickuptime_adjusted to notify the inflight rider
    . Ready (delivery and takeaway) and +10/+20 taps go through utils_common.order_management.restaurant_actions (shared with Telegram): the gate (rider on the job, food not collected) and the first-tap-wins rule live in SQL, so a stale button never runs the agent or writes to delivery_summary, and a second Ready tap is told who already pressed it instead of nudging the rider again
    . Ready buttons sent before order_number existed (no order_number in the callback) keep the old gate path (_legacy_collection_ready)
  Functions/Classes:
    . dispatch_response - Processes rider responses to delivery dispatch assignments (rules: ordelo.dispatch_actions, D48)
    . rider_request_location - Handles rider requests for location information
    . handle_shift_availability - Handles rider shift availability responses (rules: ordelo.rider_shift, R5: "Yes" from a
      rider whose status is not 'active' is refused; the other texts are unchanged)
    . handle_admin_availability - Handles admin availability responses for order notifications
    . handle_restaurant_confirmation - Processes restaurant prep time confirmation
    . restaurant_order_accept_decline_handler - Handles restaurant accept/decline responses
    . _update_restaurant_order_status - Background task for updating restaurant order status
    . handle_pickup_time_selection - Handles restaurant pickup-time selection callbacks
    . admin_collection_ready - Marks the food ready and nudges the rider agent once per dispatch (skipped after pickup)
    . _legacy_collection_ready - The pre-order_number path for old Ready buttons
    . admin_takeaway_ready - Marks a takeaway ready once and notifies the customer
    . admin_adjust_pickup_time - Handles admin pickup-time adjustment callbacks (sets restaurant_pickuptime_adjusted)
    . Ready and +10/+20 rules, and the rider / customer follow-ups, live in utils_common/order_management/restaurant_actions.py
      (shared with the Telegram taps); this file keeps only the WhatsApp parsing and replies

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . delivery_summary (table, ordelo_datamodels/delivery/delivery_summary.sql): reads, named in code (passed to a query helper)
  . rider_set_shift (function, ordelo_datamodels/availability/rider_shift.sql): calls through ordelo.rider_shift.set_shift
    (reads delivery_inflight, updates rider_master)
(end of database objects)
"""

# %%
import asyncio
from pywa_async import WhatsApp, filters
from config import logger
from pywa.types import Message
import json

# project modules
from ordelo import dispatch_actions, rider_shift
from ordelo.agents.agent_runner import run_rider_agent_w_custom_msg
from ordelo.delivery_progress import (
    GATE_REPLIES,
    DeliveryProgress,
    check_delivery_progress,
)
from ordelo_datamodels.delivery_pymodels import DeliveryDispatch
from utils_common.order_management import restaurant_actions, restaurant_decision
from utils_common.order_management.restaurant_actions import WhatsAppActor
from utils_common.waba_utils.wa_senders import CallbackButtonData
from utils_common.tz_utils import fmt_uk_time

# from utils_common.waba_utils.wa_senders import send_restaurant_pickup_time
from pywa.types import CallbackButton
# %%


IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)


async def dispatch_response(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch. This is a blocking operation. Entry point into the graph.

    The rules live in ordelo.dispatch_actions.respond_to_offer (shared with the Telegram rider bot, D48); this handler only
    parses the WhatsApp payload and sends the same texts as before.
    """
    recipient = msg.sender

    # Callback created in @delivery_hooks (/delivery-dispatch) -> wa_send_delivery_dispatch_request ->
    logger.info("Callback data: {}, recipient: {}".format(msg.data, recipient))
    callback_data: dict = json.loads(msg.data)
    out = await dispatch_actions.respond_to_offer(
        rider_id=recipient,
        dispatch_id=callback_data["dispatch_id"],
        order_number=callback_data["order_number"],
        accept=callback_data.get("status") == "accepted",
    )
    reply = dispatch_actions.whatsapp_reply(out)
    if reply:
        await wa.send_message(to=recipient, text=reply)


# %%
IS_LOCATION_REQUEST = filters.contains("/riderLocationRequest", ignore_case=False)


async def rider_request_location(wa: WhatsApp, msg: Message):
    """
    Rider's request for location. This is a blocking operation. Entry point into the graph.
    """
    # Callback created in _send_delivery_instructions, in agent_app_handlers
    callback_data: dict = json.loads(msg.data)
    dispatch_id = callback_data.get("dispatch_id")
    try:
        dispatch = DeliveryDispatch.from_dispatch_id(int(dispatch_id))
    except ValueError:
        logger.warning(f"Dispatch {dispatch_id} not found, skipping location request")
        return
    if dispatch.status == "completed":
        await wa.send_message(
            to=callback_data["recipient"],
            text="This job is expired.",
        )
        logger.info("Dispatch is complete, skipping location request")
    else:
        await run_rider_agent_w_custom_msg(
            recipient=callback_data["recipient"],
            human_msg=callback_data["human_msg"],
            dispatch_id=int(dispatch_id),
        )


# %%
IS_CANCEL_CONFIRM = filters.contains("/riderCancelConfirm", ignore_case=False)


async def rider_cancel_confirm(wa: WhatsApp, msg: Message):
    """A confirmation tap is valid only for the rider's own active dispatch."""
    from ordelo.agents import rider_threads
    data = json.loads(msg.data)
    dispatch_id = int(data["dispatch_id"])
    thread = await rider_threads.for_dispatch(dispatch_id)
    if thread is None or thread.rider_id != msg.sender or not thread.is_active or thread.dispatch_status == "completed":
        await wa.send_message(to=msg.sender, text="This job is expired.")
        return
    await run_rider_agent_w_custom_msg(recipient=msg.sender, human_msg=data["human_msg"], thread_id=thread.thread_id, cancel_tap=True)


IS_SHIFT_AVAILABILITY = filters.contains("/shiftAvailability", ignore_case=False)


SHIFT_YES_TEXT = "Great! You will receive notifications for new jobs."
SHIFT_NO_TEXT = "Ok. You will not receive job notifications for the next 24 hrs."
SHIFT_NOT_ACTIVE_TEXT = (
    "Your rider account is not active yet, so you won't receive job notifications. Ordelo will let you know when it is."
)


async def handle_shift_availability(wa: WhatsApp, msg: Message):
    """The rider's answer to the shift question. The rules (status gate, on-a-job check) live in rider_set_shift()
    (ordelo.rider_shift, R5); the texts are the ones WhatsApp riders always got, plus one for a rider who is not active."""
    # Callback created in enquire_shift_availability, in wa_senders.py
    callback_data: dict = json.loads(msg.data)
    recipient = callback_data["recipient"]
    human_msg = callback_data["human_msg"]
    out = await rider_shift.set_shift(recipient, on=human_msg == "Yes")
    if out.result == rider_shift.NOT_ACTIVE:
        await wa.send_message(to=recipient, text=SHIFT_NOT_ACTIVE_TEXT)
        logger.info(f"Rider {recipient} tried to start a shift but is {out.status!r}, not active")
    elif out.result == rider_shift.ON_JOB:
        await wa.send_message(
            to=recipient,
            text=f"You are currently on a job for order {out.order_number}. Please complete the job first.",
        )
        logger.info(f"Rider {recipient} tried to end shift but is on job {out.order_number}")
    elif human_msg == "Yes":  # on, or not_found (unknown number: the same reply as before, nothing written)
        await wa.send_message(to=recipient, text=SHIFT_YES_TEXT)
        logger.info(f"Started shift status for rider {recipient} ({out.result})")
    else:  # off, or not_found
        await wa.send_message(to=recipient, text=SHIFT_NO_TEXT)
        logger.info(f"Ended shift status for rider {recipient} ({out.result})")


# %%
IS_ADMIN_AVAILABILITY = filters.contains("/adminAvailability", ignore_case=False)


async def handle_admin_availability(wa: WhatsApp, msg: Message):
    # Callback created in enquire_admin_availability, in wa_senders.py
    callback_data: dict = json.loads(msg.data)
    recipient = callback_data["recipient"]
    await msg.reply(
        text="Great! You will receive notification for new orders for the next 24 hrs!"
    )
    logger.info(f"Admin availability confirmed for {recipient}")


_STATUS_TO_DECISION = {"restaurant_accept": "accept", "restaurant_decline": "decline"}


async def _update_restaurant_order_status(
    order_number: str,
    status: str,
    msg: Message,
    order_type: str = "delivery",
):
    """Background task: record an admin's Accept/Decline tap through the shared decision function.

    The first decision on any channel wins (restaurant_decision.decide). A tap that loses is told who decided.
    """
    decision = _STATUS_TO_DECISION.get(status)
    if decision is None:
        logger.error(f"Ignoring restaurant order status {status!r} for {order_number} ({order_type})")
        return
    try:
        outcome = await restaurant_decision.decide(
            order_number, order_type, decision, msg.sender, "whatsapp"
        )
        if outcome.result == "ok":
            logger.info(
                f"Restaurant order status updated ({order_type}): {order_number} -> {status}"
            )
        elif outcome.result == "already_decided":
            await msg.reply(
                text=f"Order already {restaurant_decision.describe(outcome.state, outcome.decided_by)}"
            )
            logger.info(
                "Skipped restaurant order status update for %s (%s); already decided: %s",
                order_number,
                order_type,
                outcome.state,
            )
        else:
            logger.error(
                f"Restaurant order {order_number} ({order_type}) not found for status update"
            )
    except Exception as e:
        logger.error(
            f"Failed to update restaurant order status for {order_number} ({order_type}): {e}"
        )


# %% Restaurant order confirmation
IS_RESTAURANT_ORDER_ACCEPT_DECLINE = filters.contains(
    "/RestaurantOrder", ignore_case=False
)


async def restaurant_order_accept_decline_handler(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_restaurant_order_confirmation, in utils_common.waba_utils.wa_templates.restaurant_confirmation_template

    order_number = callback_data.order_number
    order_time = callback_data.order_time
    recipient = msg.sender
    order_type = getattr(callback_data, "order_type", "delivery")

    logger.info(f"Restaurant order confirmation ({order_type}): {order_number}")

    if "Accept" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(
                order_number, "restaurant_accept", msg, order_type=order_type
            )
        )

    elif "Decline" in callback_data.action:
        asyncio.create_task(
            _update_restaurant_order_status(
                order_number, "restaurant_decline", msg, order_type=order_type
            )
        )

    return


# %% Handle pickup time selection. The pickup_time needs to be updated in delivery_summary table
IS_PICKUP_TIME = filters.contains("/PickupTime", ignore_case=False)


async def handle_pickup_time_selection(wa: WhatsApp, msg: Message):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(msg.data))
    # Callback data created in send_pickup_time_selection, in utils_common.waba_utils.wa_senders

    order_number = callback_data.order_number
    pickup_time = callback_data.pickup_time
    recipient = msg.sender
    order_type = getattr(callback_data, "order_type", "delivery")

    logger.info(
        f"Updating pickup time for {order_type} order {order_number} to {pickup_time}",
    )

    try:
        outcome = await restaurant_decision.set_pickup(
            order_number, order_type, pickup_time, recipient, "whatsapp"
        )
        if outcome.result == "ok":
            await msg.reply(text="Pickup time updated")
            logger.info(
                "Pickup time updated for %s order %s to %s",
                order_type,
                order_number,
                pickup_time,
            )
        elif outcome.result in ("already_set", "not_accepted"):
            await msg.reply(text="Pickup time already updated")
            logger.info(
                "Skipped pickup time update for %s (%s); %s (state %s)",
                order_number,
                order_type,
                outcome.result,
                outcome.state,
            )
        else:
            logger.error(
                f"Order {order_number} ({order_type}) not found for pickup time update"
            )
    except Exception as e:
        logger.error(
            f"Failed to update pickup time for order {order_number} ({order_type}): {e}"
        )


# %%
IS_ADMIN_COLLECTION_READY = filters.contains("/AdminCollectionReady", ignore_case=False)


async def admin_collection_ready(
    msg: WhatsApp, callback: CallbackButton[CallbackButtonData]
):
    """
    Handles the admin "Ready - Notify Rider" tap.

    The receipt message keeps its buttons forever, so an admin can tap this long
    after the delivery has finished. restaurant_actions.ready() decides in SQL:
    the rider must still be on the job and the food not collected, and only the
    FIRST tap per dispatch nudges the rider (a second tap is told who pressed it).
    Buttons sent before order_number was added to this callback fall back to the
    old rider_id gate (_legacy_collection_ready).
    """
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(callback.data))

    order_number = getattr(callback_data, "order_number", None)
    if order_number is None:
        return await _legacy_collection_ready(callback_data, callback)

    try:
        out = await restaurant_actions.ready(order_number, "delivery", WhatsAppActor(callback.sender))
    except Exception as e:
        logger.error(f"Ready tap failed for order {order_number}: {e}")
        await callback.reply(text=GATE_REPLIES[DeliveryProgress.UNKNOWN])
        return
    reply = restaurant_actions.ready_reply_text(out)
    if reply:
        logger.info(f"Admin {callback.sender} Ready tap for {order_number}: {out.result}; replied {reply!r}")
        await callback.reply(text=reply)
    return


async def _legacy_collection_ready(
    callback_data: CallbackButtonData, callback: CallbackButton[CallbackButtonData]
):
    """Ready buttons created before order_number was in the callback: gate on the rider's inflight row, as before."""
    progress, _row = await check_delivery_progress(
        rider_id=callback_data.rider_id,
        order_number=None,
    )
    if progress is not DeliveryProgress.AWAITING_PICKUP:
        logger.info(
            f"Rider {callback_data.rider_id} food-ready tap while {progress}; "
            "skipping admin food-ready notification"
        )
        await callback.reply(text=GATE_REPLIES[progress])
        return

    await run_rider_agent_w_custom_msg(
        recipient=callback_data.rider_id,
        human_msg=f"call `tool notify_food_ready_for_pickup`. Rider should hurry to {callback_data.restaurant_name} to pickup the food.",
    )
    return


# %% Handle admin pickup-time adjustment (after pickup_time already set)
IS_ADMIN_ADJUST_PICKUP_TIME = filters.contains(
    "/AdminAdjustPickupTime", ignore_case=False
)


async def admin_adjust_pickup_time(
    msg: WhatsApp, callback: CallbackButton[CallbackButtonData]
):
    """
    Handles a restaurant admin adjusting an already-set delivery pickup time.

    The button callback (created in admin_order_reciept) carries a precomputed
    new pickup_time (+10/+20 mins) and the order_number. The buttons never
    expire, so restaurant_actions.adjust_pickup() decides in SQL: if the order
    is no longer inflight, or the food has already been picked up, no write
    happens at all -- no delivery_summary update, no trigger_restaurant_updates
    fire, no rider notification. A tap that would not change the pickup time
    ('unchanged') also writes nothing and tells the rider nothing. Otherwise SQL
    updates delivery_summary.pickup_time and sets restaurant_confirmation_status
    to 'restaurant_pickuptime_adjusted', which fires trigger_restaurant_updates ->
    /delivery-hooks/restaurant-confirmation-request ->
    _handle_restaurant_pickuptime_adjusted so the inflight rider is notified.
    Lifecycle 'status' and restaurant_admin (who accepted) are left unchanged.
    """
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(callback.data))

    order_number = getattr(callback_data, "order_number", None)
    pickup_time = getattr(callback_data, "pickup_time", None)
    recipient = callback.sender

    if not order_number or not pickup_time:
        await callback.reply("Missing order or pickup time in callback. Please retry.")
        logger.error(
            "AdminAdjustPickupTime callback missing order_number/pickup_time",
            extra={"order_number": order_number},
        )
        return

    try:
        out = await restaurant_actions.adjust_pickup(order_number, WhatsAppActor(recipient), target=pickup_time)
    except Exception as e:
        logger.error(f"Failed to adjust pickup time for order {order_number}: {e}")
        await callback.reply("Failed to update pickup time. Please retry.")
        return

    if out.result in ("ok", "unchanged"):
        await callback.reply(text=f"Pickup time updated to {fmt_uk_time(out.pickup_time or pickup_time)}")
        logger.info(
            "Admin %s adjusted pickup time for %s to %s (%s)",
            recipient,
            order_number,
            pickup_time,
            out.result,
        )
        return

    logger.info(
        f"Admin {recipient} tapped adjust pickup time for {order_number} "
        f"while {out.result}/{out.progress}; no update applied"
    )
    await callback.reply(text=restaurant_actions.not_done_reply_text(out))
    return


IS_ADMIN_TAKEAWAY_READY = filters.contains("/AdminTakeawayReady", ignore_case=False)


async def admin_takeaway_ready(
    wa: WhatsApp, callback: CallbackButton[CallbackButtonData]
):
    callback_data: CallbackButtonData = CallbackButtonData(**json.loads(callback.data))
    order_number = getattr(callback_data, "order_number", None)
    order_id = None
    if order_number and "-" in order_number:
        order_id = "-".join(order_number.split("-")[1:])
    rest_ref = getattr(callback_data, "rest_ref", None)

    if not rest_ref and order_number and "-" in order_number:
        rest_ref = order_number.split("-")[0]

    if not order_id:
        await callback.reply("Missing order number in callback. Please retry.")
        logger.error(
            "AdminTakeawayReady callback missing/invalid order_number",
            extra={"order_number": order_number},
        )
        return

    if not rest_ref:
        await callback.reply("Missing restaurant reference in callback. Please retry.")
        logger.error(
            "AdminTakeawayReady callback missing rest_ref",
            extra={"order_id": order_id, "order_number": order_number},
        )
        return

    try:
        out = await restaurant_actions.ready(order_number, "takeaway", WhatsAppActor(callback.sender))
    except Exception as e:
        logger.error(
            f"Failed to notify takeaway ready for order_id={order_id}, order_number={order_number}: {e}"
        )
        await callback.reply("Failed to notify customer. Please retry.")
        return
    if out.result == "ok":
        if out.follow_up_failed:  # Ready is recorded (a retry would only say "already ready"), so say what to do instead
            await callback.reply("Marked ready, but the customer notification failed. Please contact the customer.")
        else:
            await callback.reply("Customer notification request sent.")
        return
    await callback.reply(text=restaurant_actions.ready_reply_text(out))
