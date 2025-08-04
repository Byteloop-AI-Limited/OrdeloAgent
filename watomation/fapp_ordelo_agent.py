"""
FastAPI WhatsApp Agent integration for Ordelo delivery system
    . Initializes and configures the FastAPI app with WhatsApp messaging capabilities
    . Integrates pywa_async for WhatsApp event and flow handling
    . Manages application state including DB connection pools and graph checkpoints
    . Sets up routers for delivery, location, and alert webhooks
    . Registers WhatsApp message handlers, callback handlers, and flow request handlers
    . Provides debug endpoints for diagnostics and testing
    . Entry point for running OrdeloAgent locally or in production
    . Integrates with PostgreSQL database triggers via webhook pattern
  Functions/Classes:
    . custom_404_handler - Handles 404 errors with custom template
    . get_details - Returns WhatsApp business account details
    . debug_state_path - Provides debug information for agent state
    . app - FastAPI application instance
    . wa - WhatsApp client instance with handlers for messages and flows
"""

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn
from pywa_async import WhatsApp, filters
from pywa_async import handlers
from pywa.types.flows import FlowRequestActionType

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config import (
    waba_business_settings,
    pg_settings,
    client_ordelo,
)
from ordelo.agents.rider_agent import builder
from ordelo.agent_app_handlers import debug_state, debug_state_by_thread

from watomation.routers import delivery_hooks, location_hooks, twilio_webhook
from watomation.on_message_wa_handler import (
    reset_thread,
    test_delivery,
    process_wa_msg,
    test_flow,
    clear_dispatch,
    send_live_map_location,
)
from watomation.on_callback_wa_handler import (
    dispatch_response,
    rider_request_location,
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
app.include_router(twilio_webhook.router, prefix="/twilio-webhook")

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
)

TEST_DELIVERY = filters.contains("/test", ignore_case=True)
CLEAR_DISPATCH = filters.contains("/cleardis", ignore_case=True)
LIVE_LOCATION = filters.contains("/live", ignore_case=True)
TEST_FLOW = filters.contains("/flow", ignore_case=True)

WHEN_RESET = filters.contains("/reset", ignore_case=True)
IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)
IS_LOCATION_REQUEST = filters.contains("/riderLocationRequest", ignore_case=False)

# %% Add WA On Msg handlers
wa.add_handlers(
    handlers.MessageHandler(callback=reset_thread, filters=WHEN_RESET),
    handlers.MessageHandler(callback=test_delivery, filters=TEST_DELIVERY),
    handlers.MessageHandler(callback=clear_dispatch, filters=CLEAR_DISPATCH),
    handlers.MessageHandler(callback=test_flow, filters=TEST_FLOW),
    handlers.MessageHandler(callback=send_live_map_location, filters=LIVE_LOCATION),
    handlers.MessageHandler(callback=process_wa_msg),
    handlers.CallbackButtonHandler(
        callback=dispatch_response, filters=IS_DISPATCH_RESPONSE
    ),
    handlers.CallbackButtonHandler(
        callback=rider_request_location, filters=IS_LOCATION_REQUEST
    ),
    handlers.FlowCompletionHandler(callback=on_customer_address_flow_completion),
)

# print_chat_opened = lambda _, msg: print(msg)
# wa.add_handlers(handlers.ChatOpenedHandler(print_chat_opened))

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
    business_phone_number = await wa.get_business_phone_number()
    phone_id = waba_business_settings.phone_id
    phone_num = business_phone_number.display_phone_number
    bus_name = business_phone_number.verified_name
    callback_url_on_waba = business_phone_number.webhook_configuration["application"]
    callback_url = waba_business_settings.callback_url

    return {
        "phone_id": str(phone_id),
        "display_phone_num": phone_num,
        "verified_name": bus_name,
        "callback_url": callback_url,
        "callback_url_on_waba": callback_url_on_waba,
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


# %% Debug state


@app.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    debug_stack = await debug_state(recipient, graph, pool)
    return debug_stack


@app.get("/debug-state-by-thread")
async def debug_state_by_thread_path(
    recipient: Optional[str] = "447448440754", thread_id: Optional[str] = "thread_id"
):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    debug_stack = await debug_state_by_thread(recipient, thread_id, graph, pool)
    return debug_stack


# %%
if __name__ == "__main__":
    uvicorn.run(
        "watomation.fapp_ordelo_agent:app", host="0.0.0.0", port=3100, reload=True
    )
