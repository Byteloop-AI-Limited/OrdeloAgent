# %% Imports
import logging
from contextlib import asynccontextmanager
from typing import Optional
import json
import base64
from datetime import datetime
import psycopg

import uvicorn as uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from pywa.types import Message
from pywa_async import WhatsApp, filters
from pywa import WhatsApp as WhatsAppNonSync
from utils_common.thread_management import ThreadHandler
from ordelo_datamodels.location_pymodels import Location
import pickle
from watomation.routers import delivery_hooks, location_hooks
from ordelo.agents.rider_agent import builder
from langgraph.checkpoint.memory import MemorySaver
import asyncio


from config import (
    project_settings,
    logger,
    pg_settings,
    waba_business_settings,
)

from utils_common.wa_send.wa_senders import process_dispatch_response_from_rider, process_dispatch_response_from_rider_sync
from utils_common.db_utils.sbase_rest_ops import sbase_insert, sbase_update, sbase_get

# %% Setup html templates
templates = Jinja2Templates(directory=str(f"{project_settings.project_root}/elai/pages_template"))

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
    # Initialize the pool
    pool = AsyncConnectionPool(
        conninfo=pg_settings.db_uri,
        # min_size=20,
        # max_size=200,
        # max_lifetime=0,
        # max_idle=0,
        kwargs=pg_settings.connection_kwargs,
        open=False,
    )

    pool_sync = ConnectionPool(pg_settings.db_uri)
    pool_sync.open()


    # Explicitly open the pool
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    thread_handler = ThreadHandler(pool)
    # graph = builder.compile(checkpointer=checkpointer)
    graph = builder.compile(checkpointer=MemorySaver())

    # Store it in the app state
    app.state.pool = pool
    app.state.pool_sync = pool_sync
    app.state.checkpointer = checkpointer
    app.state.thread_handler = thread_handler
    app.state.graph = graph

    # Yield to start the application
    try:
        yield
    finally:
        # Close the pool on shutdown
        await pool.close()

# %% Define Fastapi app with lifespan and routers

app = FastAPI(title="OrdeloAgent", lifespan=lifespan)
app.include_router(delivery_hooks.router, prefix="/delivery-hooks")
app.include_router(location_hooks.router, prefix="/pub")

recipient='447448440754'

# %% Local runs
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
        # callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
    )
else:
    wa: WhatsApp = WhatsApp(
        token=waba_business_settings.token,
        server=app,
        verify_token=waba_business_settings.verify_token,
        phone_id=waba_business_settings.phone_id,
        # callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=3,
        app_id=waba_business_settings.app_id,
        app_secret=waba_business_settings.app_secret,
        continue_handling=False,
    )
    
# %% details
@app.get("/details")
async def get_details():
    business_phone_number = await wa.get_business_phone_number()
    phone_id = waba_business_settings.phone_id
    phone_num = business_phone_number.display_phone_number
    bus_name = business_phone_number.verified_name
    callback_url = business_phone_number.webhook_configuration["application"]
    return {
        "phone_id": str(phone_id),
        "display_phone_num": phone_num,
        "verified_name": bus_name,
        "callback_url": callback_url,
    }

# %% WA Overrides - reset, payment complete, reservation confirmation

# TEST_DELIVERY = filters.contains("/testdelivery", ignore_case=True)
TEST_DELIVERY = filters.contains("/test", ignore_case=True)
WHEN_RESET = filters.contains("/reset", ignore_case=True)
PAYMENT_COMPLETE = filters.contains("/paid", ignore_case=True)
RESERVATION_CONFIRMED = filters.contains("/confirm", ignore_case=True)
IS_DISPATCH_RESPONSE = filters.contains("/dispatchResponse", ignore_case=False)


@wa.on_message(TEST_DELIVERY)
async def test_delivery(wa: WhatsApp, msg: Message):
    # reset the status of test delivery to unassigned
    await sbase_update(
        update_fields={"status": "unassigned", "dispatch_id": None, "rider_id": None},
        table_name="delivery_detail",
        order_number='test123'
    )
    await sbase_update(
        update_fields={"status": "completed"},
        table_name="delivery_dispatch",
        status='assigned'
    )
    # Create a delivery dispatchs
    delivery_dispatch = {
        'order_number': 'test123',
        'rider_id': msg.sender,
        'rider_payout': 0.5,
        'distance': 0.5,
        'status': 'unassigned'
    }
    await sbase_insert("delivery_dispatch", delivery_dispatch)
    # todo
    delivery_dispatch = {
        'order_number': 'test123',
        'rider_id': '447448440754',
        'rider_payout': 0.5,
        'distance': 0.5,
        'status': 'unassigned'
    }
    await sbase_insert("delivery_dispatch", delivery_dispatch)


@wa.on_message(WHEN_RESET)
async def reset_thread(wa: WhatsApp, msg: Message):
    logger.info("=============== reset the thread ===============")
    recipient = msg.from_user.wa_id
    pool = app.state.pool
    thread_handler = ThreadHandler(pool)

    await thread_handler.make_threads_inactive(from_number=recipient)
    await wa.send_message(to=recipient, text="Starting new conversation")


# %% WA Handlers

@wa.on_message()
async def echo_msg(wa: WhatsApp, msg: Message):
    recipient = msg.sender
    logger.info(msg)
    await wa.send_text(
        to=recipient,
        text=msg.text.lower()
    ) 

@wa.on_callback_button(IS_DISPATCH_RESPONSE)
def callback_selection(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch. This is a blocking operation.
    """
    logger.info(msg)
    recipient = msg.sender
    callback_data: dict = json.loads(msg.data)

    process_dispatch_response_from_rider_sync(
        recipient=recipient,
        callback_data=callback_data
    )
    # toDo - initilize the graph here, avoid another trigger from the detail table.
    
# @wa.on_callback_button(IS_DISPATCH_RESPONSE)
# async def callback_selection(wa: WhatsApp, msg: Message):
#     """
#     Rider's response to delivery dispatch. This is a blocking operation.
#     """
#     logger.info(msg)
#     recipient = msg.sender
#     callback_data: dict = json.loads(msg.data)

#     await process_dispatch_response_from_rider(
#         recipient=recipient,
#         callback_data=callback_data,
#         _async_wa_client=wa
#     )

# %%

if __name__ == "__main__":
    uvicorn.run("watomation.app_ordelo_agent:app", host="0.0.0.0", port=8000, reload=True)
