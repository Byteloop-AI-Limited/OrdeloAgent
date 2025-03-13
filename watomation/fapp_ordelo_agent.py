from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging

import uvicorn

from pywa.types import ChatOpened
from pywa_async import WhatsApp, filters
from pywa_async import handlers
from pywa.types.flows import FlowRequest, FlowResponse, FlowRequestActionType, FlowCompletion
from typing import Optional

from config import (
    logger,
    project_settings,
    waba_business_settings,
)

from watomation.init_app_state import init_app_state
from watomation.routers import delivery_hooks, location_hooks
from watomation.on_message_wa_handler import reset_thread, test_delivery, process_wa_msg, live_location
from watomation.on_callback_wa_handler import dispatch_response
from watomation.on_flow_request_wa_handler import on_customer_address_flow, on_customer_address_flow_data_exchange, on_customer_address_flow_completion


from ordelo.agent_app_handlers import debug_state

# %%
# Configure logging settings
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
# https://10hiths-app.up.railway.app/

# %% define fastapi
POOL_MIN_SIZE = 10
POOL_MAX_SIZE = 25

# %% Define Lifespan Events


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize app state resources
    pool, pool_sync, checkpointer, thread_handler, graph, client = await init_app_state()
    
    # Store resources in the app state
    app.state.pool = pool
    app.state.pool_sync = pool_sync
    app.state.client = client
    app.state.checkpointer = checkpointer
    app.state.thread_handler = thread_handler
    app.state.graph = graph
    app.state.wa = wa

    # Yield to start the application
    try:
        yield
    finally:
        # Close the pool on shutdown
        if pool:
            await pool.close()

# Define and set the app, call import soon after
app = FastAPI(title="OrdeloAgent", lifespan=lifespan)

# %% Add routers
app.include_router(delivery_hooks.router, prefix="/delivery-hooks")
app.include_router(location_hooks.router, prefix="/location-hooks")

# %% DEFINE WA
if __name__ == "__main__":
    from dotenv import load_dotenv

    project_root = project_settings.project_root
    load_dotenv(f"{project_root}/.env")
    logger.info("Starting OrdeloAgent locally ...")

    wa: WhatsApp = WhatsApp(
        token=waba_business_settings.token,
        server=app,
        verify_token=waba_business_settings.verify_token,
        phone_id=waba_business_settings.phone_id,
        callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
        business_private_key=waba_business_settings.private_key,
        # business_private_key=open("/home/basal/PycharmProjects/OrdeloAgent/data/certs/private.pem").read(),
        business_private_key_password=waba_business_settings.private_key_password
    )
else:
    wa: WhatsApp = WhatsApp(
        token=waba_business_settings.token,
        server=app,
        verify_token=waba_business_settings.verify_token,
        phone_id=waba_business_settings.phone_id,
        callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
        business_private_key=waba_business_settings.private_key,
        # business_private_key=open("/home/basal/PycharmProjects/OrdeloAgent/data/certs/private.pem").read(),
        business_private_key_password=waba_business_settings.private_key_password
    )


TEST_DELIVERY = filters.contains("/test", ignore_case=True)
LIVE_LOCATION = filters.contains("/live", ignore_case=True)

WHEN_RESET = filters.contains("/reset", ignore_case=True)
IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)

# %% Add WA On Msg handlers
wa.add_handlers(
    handlers.MessageHandler(callback=reset_thread, filters=WHEN_RESET),
    handlers.MessageHandler(callback=test_delivery, filters=TEST_DELIVERY),
    handlers.MessageHandler(callback=live_location, filters=LIVE_LOCATION),
    handlers.MessageHandler(callback=process_wa_msg),
    handlers.CallbackButtonHandler(callback=dispatch_response, filters=IS_DISPATCH_RESPONSE),
    handlers.FlowCompletionHandler(callback=on_customer_address_flow_completion),
)

print_chat_opened = lambda _, msg: print(msg)
wa.add_handlers(handlers.ChatOpenedHandler(print_chat_opened))

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
    filters=None
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
        "callback_url_on_waba": callback_url_on_waba
    }


@app.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    graph = app.state.graph
    pool = app.state.pool
    debug_stack = await debug_state(recipient, graph, pool)
    return debug_stack

# %% On chat opened
# @wa.on_chat_opened
# async def chat_opened_handler(wa: WhatsApp, chat_opened: ChatOpened):
#     # logger.success(f"The user {chat_opened.from_user.wa_id} just opened a chat with us!")
#     logger.success(f"The user just opened a chat with us!")
#     return 


# %%
if __name__ == "__main__":
    uvicorn.run("watomation.fapp_ordelo_agent:app", host="0.0.0.0", port=3100, reload=True)
