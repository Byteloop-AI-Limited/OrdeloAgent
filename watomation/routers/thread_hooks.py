"""
Thread webhook handler module for the Ordelo rider agent.
    . Processes thread lifecycle webhook events from database triggers
    . Runs system message injections for a thread
    . Sends goodbye messages to users via WhatsApp
    . Implements FastAPI router endpoints for thread management
    . Provides debug endpoints for state inspection by recipient or thread_id
  Functions/Classes:
    . RunSystemMessageRequest - Input model for system message execution
    . run_system_message - Executes rider graph with a system message
    . debug_state_values_path - Debug endpoint to view conversation state values
    . debug_state_path - Debug endpoint to view complete conversation state
    . debug_admin_state_path - Debug endpoint to view admin conversation state
    . debug_state_by_thread_path - Debug endpoint to view state by thread_id

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . thread (table, restaurant-agents): reads, named in code (passed to a query helper)
(end of database objects)
"""

# %%
from typing import Optional

from config import logger
from fastapi import APIRouter, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel

from config import client_ordelo, pg_settings
from ordelo.agents.agent_runner import (
    debug_state,
    debug_state_values,
    debug_thread,
    run_rider_agent_w_custom_msg,
)
from ordelo.agents.rider_agent import builder
from utils_common.lg_utils import (
    get_state_values,
    shorten_state_messages,
)

# %% Define Dependencies and routes

router = APIRouter(tags=["thread-hooks"])


# %%
class RunSystemMessageRequest(BaseModel):
    thread_id: str
    recipient: Optional[str] = None
    update_message: str
    state_update_dict: Optional[dict] = None


@router.post(
    "/run-system-message",
    summary="Run rider graph with a system message",
    description="""
    Runs the rider graph with a system message for a given thread_id.
    If recipient is not provided, it is fetched from the thread table.
    """,
)
async def run_system_message(request: RunSystemMessageRequest):
    recipient = request.recipient
    if not recipient:
        result = (
            client_ordelo.table("thread")
            .select("thread_id", "recipient")
            .eq("thread_id", request.thread_id)
            .eq("is_active", True)
            .execute()
        )
        logger.debug(f"Thread fetch result: {result}")
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail=f"Thread not found or inactive: {request.thread_id}",
            )
        recipient = result.data[0]["recipient"]

    # Run exactly the named thread (R2): no longer reduced to "the rider's thread" by phone.
    ai_response = await run_rider_agent_w_custom_msg(
        recipient=recipient,
        system_msg=request.update_message,
        state_update_dict=request.state_update_dict,
        thread_id=request.thread_id,
    )
    if ai_response is None:
        raise HTTPException(status_code=404, detail=f"Thread not found or inactive: {request.thread_id}")
    return {
        "status": "success",
        "thread_id": request.thread_id,
        "recipient": recipient,
        "response": ai_response,
    }


@router.get("/debug-state-values")
async def debug_state_values_path(recipient: Optional[str] = "447448440754"):
    debug_stack = await debug_state_values(recipient)
    return debug_stack


@router.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    debug_stack = await debug_state(recipient)
    return debug_stack


@router.get("/debug-thread")
async def debug_thread_path(thread_id: str):
    debug_stack = await debug_thread(thread_id)
    return debug_stack


@router.get("/debug-admin-state")
async def debug_admin_state_path(recipient: Optional[str] = "447448440754"):
    debug_stack = await debug_state(recipient)
    return debug_stack


@router.get("/debug-state-by-thread")
async def debug_state_by_thread_path(thread_id: str):
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    # Get thread using thread_id
    thread = (
        client_ordelo.table("thread")
        .select("thread_id, recipient")
        .eq("thread_id", thread_id)
        .execute()
        .data[0]
    )

    recipient = thread["recipient"]
    config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}

    state = await graph.aget_state(config=config)

    debug_stack = {
        **get_state_values(state.values),
        "messages": shorten_state_messages(state.values["messages"]),
    }

    return debug_stack
