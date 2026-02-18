"""
FastAPI application for Ordelo WhatsApp automation service.
    . Configures FastAPI routers and WhatsApp handlers for agent workflows
    . Manages PostgreSQL checkpoints and Supabase-backed thread access
    . Exposes diagnostic endpoints for debugging agent state and flows
    . Serves as entry point when running OrdeloAgent with WhatsApp integration
  Functions/Classes:
    . app - FastAPI application instance
    . custom_404_handler - Handles 404 errors with template response
    . get_details - Returns WhatsApp business profile and callback info
    . get_threads - Lists conversation threads for a recipient
    . get_restaurant_details - Returns restaurant config and webhook URLs
    . echo_request - Echoes inbound payloads for validation
    . debug_state_path - Gets LangGraph debug stack for a recipient
    . debug_state_by_thread_path - Gets debug stack for a specific thread
    . wa - WhatsApp client configured with message, callback, and flow handlers
"""

import logging
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn
from pywa_async import WhatsApp, filters
from pywa_async import handlers
from pywa.types.flows import FlowRequestActionType

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config import waba_business_settings, pg_settings, client_ordelo
from ordelo.agents.rider_agent import builder
from ordelo.agent_app_handlers import (
    debug_state,
    debug_state_by_thread,
)
from utils_common.waba_utils.wa_senders import enquire_shift_availability_non_template
from watomation.routers import (
    delivery_hooks,
    location_hooks,
    takeaway_hooks,
    twilio_webhook,
    order_hooks,
    payment_hooks,
    thread_hooks,
)

from watomation.on_message_wa_handler import (
    reset_thread,
    test_delivery,
    process_wa_msg,
    test_flow,
    clear_dispatch,
    send_live_map_location,
    send_closed_message,
    OUT_OF_HOURS_FILTER,
    WHEN_RESET,
    TEST_DELIVERY,
    CLEAR_DISPATCH,
    LIVE_LOCATION,
    TEST_FLOW,
)
from watomation.on_callback_wa_handler import (
    dispatch_response,
    rider_request_location,
    handle_shift_availability,
    handle_admin_availability,
    admin_collection_ready,
    admin_takeaway_ready,
    restaurant_order_accept_decline_handler,
    handle_pickup_time_selection,
    IS_DISPATCH_RESPONSE,
    IS_LOCATION_REQUEST,
    IS_SHIFT_AVAILABILITY,
    IS_ADMIN_AVAILABILITY,
    IS_RESTAURANT_ORDER_ACCEPT_DECLINE,
    IS_PICKUP_TIME,
    IS_ADMIN_COLLECTION_READY,
    IS_ADMIN_TAKEAWAY_READY,
)
from watomation.on_flow_request_wa_handler import (
    on_customer_address_flow,
    on_customer_address_flow_data_exchange,
    on_customer_address_flow_completion,
)
from watomation.on_flow_request_postcode_search import (
    on_pc_search_init,
    on_ip_pc,
)


# %%
# Configure logging settings
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# %% define fastapi
POOL_MIN_SIZE = 10
POOL_MAX_SIZE = 25

# %% Define Lifespan Events

# Define and set the app, call import soon after
app = FastAPI(title="OrdeloAgent")

templates = Jinja2Templates(directory="watomation/routers/templates")


@app.exception_handler(404)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        "404.html",
        {"request": request},
        status_code=404,
    )


# %% Add routers
app.include_router(delivery_hooks.router, prefix="/delivery-hooks")
app.include_router(location_hooks.router, prefix="/location-hooks")
app.include_router(takeaway_hooks.router, prefix="/takeaway-hooks")
app.include_router(thread_hooks.router, prefix="/thread-hooks")
app.include_router(twilio_webhook.router, prefix="/twilio-webhook")
app.include_router(order_hooks.router, prefix="/order-hooks")
app.include_router(payment_hooks.router, prefix="/payment-hooks")

# %% DEFINE WA
wa: WhatsApp = WhatsApp(
    token=waba_business_settings.token,
    server=app,
    verify_token=waba_business_settings.verify_token,
    phone_id=waba_business_settings.phone_id,
    validate_updates=False,
    continue_handling=False,
    business_private_key=waba_business_settings.private_key,
    business_private_key_password=waba_business_settings.private_key_password,
    # handlers_modules=[on_message_wa_handler, on_flow_request_wa_handler]
)

SHIFT_UPDATE = filters.contains("/shift", ignore_case=True)


# %% Add WA On Msg handlers
wa.add_handlers(
    # handlers.MessageHandler(callback=send_closed_message, filters=OUT_OF_HOURS_FILTER),
    handlers.MessageHandler(callback=reset_thread, filters=WHEN_RESET),
    handlers.MessageHandler(callback=test_delivery, filters=TEST_DELIVERY),
    handlers.MessageHandler(callback=clear_dispatch, filters=CLEAR_DISPATCH),
    handlers.MessageHandler(callback=test_flow, filters=TEST_FLOW),
    handlers.MessageHandler(callback=send_live_map_location, filters=LIVE_LOCATION),
    handlers.MessageHandler(
        callback=enquire_shift_availability_non_template, filters=SHIFT_UPDATE
    ),
    # handlers.MessageHandler(callback=process_byteloop_agent),
    handlers.MessageHandler(callback=process_wa_msg),
    handlers.CallbackButtonHandler(
        callback=admin_collection_ready,
        filters=IS_ADMIN_COLLECTION_READY,
    ),
    handlers.CallbackButtonHandler(
        callback=admin_takeaway_ready,
        filters=IS_ADMIN_TAKEAWAY_READY,
    ),
    handlers.CallbackButtonHandler(
        callback=dispatch_response, filters=IS_DISPATCH_RESPONSE
    ),
    handlers.CallbackButtonHandler(
        callback=rider_request_location, filters=IS_LOCATION_REQUEST
    ),
    handlers.CallbackButtonHandler(
        callback=handle_shift_availability, filters=IS_SHIFT_AVAILABILITY
    ),
    handlers.CallbackButtonHandler(
        callback=handle_admin_availability, filters=IS_ADMIN_AVAILABILITY
    ),
    handlers.CallbackButtonHandler(
        callback=restaurant_order_accept_decline_handler,
        filters=IS_RESTAURANT_ORDER_ACCEPT_DECLINE,
    ),
    handlers.CallbackButtonHandler(
        callback=handle_pickup_time_selection,
        filters=IS_PICKUP_TIME,
    ),
    handlers.FlowCompletionHandler(callback=on_customer_address_flow_completion),
)

# %% Add WA Flow Request handlers
wa.add_flow_request_handler(
    handlers.FlowRequestHandler(
        endpoint="/customer-address-capture",
        callback=on_customer_address_flow,
    )
).add_handler(
    callback=on_customer_address_flow_data_exchange,
    action=FlowRequestActionType.DATA_EXCHANGE,
    screen="START",
    filters=None,
)

wa.add_flow_request_handler(
    handlers.FlowRequestHandler(
        endpoint="/flows/postcode-search",
        callback=on_pc_search_init,
    )
).add_handler(
    callback=on_ip_pc,
    action=FlowRequestActionType.DATA_EXCHANGE,
    screen="START",
    filters=None,
)


# %% debug
@app.get("/details")
async def get_details():
    from config import _async_wa_client as wa
    from config.params import get_restaurant_base_url_async

    business_phone_number = await wa.get_business_phone_number()
    phone_id = waba_business_settings.phone_id
    verified_named = business_phone_number.verified_name
    phone_num = business_phone_number.display_phone_number
    webhook_configuration = business_phone_number.webhook_configuration[
        "whatsapp_business_account"
    ]
    callback_url = waba_business_settings.callback_url

    # Fetch base URLs dynamically
    elas_base_url = await get_restaurant_base_url_async("ELAS")
    ordelo_base_url = await get_restaurant_base_url_async("ORDELO")
    restaurant_menu_url = await get_restaurant_base_url_async("RESTAURANT_MENU")

    return {
        "verified_name": verified_named,
        "phone_id": str(phone_id),
        "display_phone_num": phone_num,
        "callback_url": callback_url,
        "webhook_configuration": webhook_configuration,
        "elas_base_url": elas_base_url,
        "ordelo_base_url": ordelo_base_url,
        "restaurant_menu_url": restaurant_menu_url,
    }


@app.get("/restaurant-details/{rest_ref}")
async def get_restaurant_details(rest_ref: str):
    from config.params import (
        WEBHOOK_PATHS,
        get_restaurant_base_url_async,
        get_restaurant_admins,
        get_restaurant_webhook_url_async,
    )

    rest_ref = rest_ref.upper()
    try:
        base_url = await get_restaurant_base_url_async(rest_ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    webhook_urls = {}
    for webhook_type in WEBHOOK_PATHS.keys():
        try:
            webhook_urls[webhook_type] = await get_restaurant_webhook_url_async(
                rest_ref, webhook_type
            )
        except ValueError:
            continue  # Skip if webhook type not configured for this restaurant

    if not webhook_urls:
        raise HTTPException(
            status_code=400,
            detail=f"No webhook config found for rest_ref={rest_ref}",
        )

    return {
        "rest_ref": rest_ref,
        "base_url": base_url,
        "webhook_urls": webhook_urls,
        "admins": get_restaurant_admins(rest_ref=rest_ref),
    }


# %% Reset base URL cache (diagnostic)
@app.post("/restaurant-base-url-cache/reset")
async def reset_restaurant_base_url_cache_endpoint(
    rest_ref: Optional[str] = None,
):
    """Reset the in-memory restaurant base URL cache.

    If rest_ref is provided, clears only that restaurant's cached base URL.
    If not, clears the entire cache.
    """
    from config.params import (
        reset_overwatch_list_cache,
        reset_restaurant_base_url_cache,
    )

    removed_entries = reset_restaurant_base_url_cache(rest_ref)
    removed_overwatch = reset_overwatch_list_cache()
    return {
        "scope": rest_ref.upper() if rest_ref else "ALL",
        "removed_entries": removed_entries,
        "removed_overwatch_list_entries": removed_overwatch,
    }


# %% get threads for id
@app.get("/threads")
async def get_threads(recipient: Optional[str] = "447448440754"):
    threads = (
        client_ordelo.table("thread")
        .select("thread_id, dtts")
        .eq("from_number", recipient)
        .order("dtts", desc=True)
        .execute()
    )
    return threads.data


# %%
@app.post("/echo")
async def echo_request(request: Request):
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else await request.body()
    )
    # print(f"Incoming /echo request: {request.method} {request.url}")
    # print(f"Headers: {dict(request.headers)}")
    print(f"Body: {body}")
    return {"received": body}


# %% Debug state


@app.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    debug_stack = await debug_state(recipient, graph, pool)
    return debug_stack


@app.get("/debug-state-by-thread")
async def debug_state_by_thread_path(thread_id: str):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    # Get thread using thread_id
    thread = (
        client_ordelo.table("thread")
        .select("thread_id, from_number")
        .eq("thread_id", thread_id)
        .execute()
        .data[0]
    )
    debug_stack = await debug_state_by_thread(
        thread["from_number"], thread_id, graph, pool
    )
    return debug_stack


# %%
if __name__ == "__main__":
    uvicorn.run(
        "watomation.fapp_ordelo_agent:app", host="0.0.0.0", port=3100, reload=True
    )
