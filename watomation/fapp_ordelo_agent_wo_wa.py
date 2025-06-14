"""
FastAPI WhatsApp Agent integration for Ordelo delivery system
    . Initializes and configures the FastAPI app with WhatsApp messaging capabilities
    . Integrates pywa_async for WhatsApp event and flow handling
    . Manages application state including DB connection pools and graph checkpoints
    . Sets up routers for delivery, location, and alert webhooks
    . Registers WhatsApp message handlers, callback handlers, and flow request handlers
    . Provides debug endpoints for diagnostics and testing
    . Entry point for running OrdeloAgent locally or in production

Key Components:
    . app - FastAPI application instance
    . wa - WhatsApp client instance
    . Message handlers - process_wa_msg, reset_thread, test_delivery, etc.
    . Flow handlers - on_customer_address_flow, on_pc_search_init
    . Routers - delivery_hooks, location_hooks, alert_hooks
"""

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging

import uvicorn

from typing import Optional

from ordelo.agents.rider_agent import builder
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config import (
    waba_business_settings,
    pg_settings,
)  # Added pg_settings

from watomation.routers import (
    delivery_hooks,
    location_hooks,
    whatsapp_router,
)


from ordelo.agent_app_handlers import debug_state

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
app.include_router(whatsapp_router.router, prefix="/whatsapp-router")


# %% debug
@app.get("/details")
async def get_details():
    phone_id = waba_business_settings.phone_id
    callback_url = waba_business_settings.callback_url

    return {
        "phone_id": str(phone_id),
        "callback_url": callback_url,
    }


@app.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    debug_stack = await debug_state(recipient, graph, pool)
    return debug_stack


# %%
if __name__ == "__main__":
    uvicorn.run(
        "watomation.fapp_ordelo_agent_wo_wa:app", host="0.0.0.0", port=3100, reload=True
    )
