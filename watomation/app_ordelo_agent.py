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
from psycopg_pool import AsyncConnectionPool
from pywa.types import Message
from pywa_async import WhatsApp, filters
from utils_common.thread_management import ThreadHandler
from ordelo_datamodels.location_models import Location
import pickle
from watomation.routers import delivery_hooks
from ordelo.agents.rider_agent import builder
from langgraph.checkpoint.memory import MemorySaver


from config import (
    project_settings,
    logger,
    pg_settings,
    waba_business_settings,
)

from utils_common.wa_send.wa_senders import process_dispatch_response_from_rider
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

    # Explicitly open the pool
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    thread_handler = ThreadHandler(pool)
    # graph = builder.compile(checkpointer=checkpointer)
    graph = builder.compile(checkpointer=MemorySaver())

    # Store it in the app state
    app.state.pool = pool
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

recipient='447448440754'

# Mount the delivery hooks router
app.mount("/delivery-hooks", delivery_hooks.router)

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
        webhook_challenge_delay=5,
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
        callback_url=waba_business_settings.callback_url,
        webhook_challenge_delay=5,
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

# %% Location capture
@app.post("/pub")
async def receive_pub(request: Request):
    payload = await request.json()
    pool = app.state.pool
    location = Location(**payload)
    print(location)

    try:
        # Acquire a connection from the pool
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    # Build dynamic query using fields from location
                    columns = ", ".join(location.dict().keys())
                    placeholders = ", ".join([f"%({key})s" for key in location.dict().keys()])
                    query = f"""
                        INSERT INTO driver_location ({columns})
                        VALUES ({placeholders})
                        RETURNING *;
                    """
                    await cur.execute(query, location.dict())
                    result = await cur.fetchone()
                    print(result)
                    return {"result": result}
    except Exception as e:
        # Log additional debug information for troubleshooting
        debug_info = {
            'query': query,
            'payload': location.dict(),
            'error': str(e)
        }
        print('DEBUG:', debug_info)
        raise HTTPException(status_code=500, detail=f"Insertion failed. Debug info: {debug_info}")
    
    
# %% Config page
# Insert the function definition for generating the configuration URL
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"

@app.get("/config")
async def get_config(request: Request):
    waypoints = [
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "h0me",
            "desc": "home",
            "rad": 1,
            "lat": 51.354107,
            "lon": 0.095921
        },
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "tesco",
            "desc": "tesco",
            "rad": 5,
            "lat": 51.37367242361126,
            "lon": 0.09653313354081415
        },
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "Gym",
            "desc": "Gym",
            "rad": 5,
            "lat": 51.37355872938557,
            "lon": 0.09813191393856706
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
    
    stop_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": False,
        "usePassword" : False,
        "monitoring": -1,
        "username": "NA",
        "password": "",
        "url": "",
    }
    
    start_href = generate_config_href(start_job_config)
    stop_href = generate_config_href(stop_job_config)
    
    return templates.TemplateResponse("get-config.html", {"request": request, "start_href": start_href, "stop_href": stop_href})



# %% WA Overrides - reset, payment complete, reservation confirmation

TEST_DELIVERY = filters.contains("/testdelivery", ignore_case=True)
WHEN_RESET = filters.contains("/reset", ignore_case=True)
PAYMENT_COMPLETE = filters.contains("/paid", ignore_case=True)
RESERVATION_CONFIRMED = filters.contains("/confirm", ignore_case=True)


@wa.on_message(TEST_DELIVERY)
async def test_delivery(wa: WhatsApp, msg: Message):
    # Create a delivery dispatch
    delivery_dispatch = {
        'order_number': 'test123',
        'rider_id': msg.sender,
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
async def callback_selection(wa: WhatsApp, msg: Message):
    """
    Rider's response to delivery dispatch
    """
    recipient = msg.sender
    callback_data = json.loads(msg.data)
    _dispatch_id = callback_data['dispatch_id']

    # Process Rider's response
    await process_dispatch_response_from_rider(
        recipient=recipient,
        callback_data=callback_data
    )

    # await wa.send_text(
    #     to=recipient,
    #     text=msg.text.lower()
    # )

# %%

if __name__ == "__main__":
    uvicorn.run("watomation.app_ordelo_agent:app", host="0.0.0.0", port=8000, reload=True)
