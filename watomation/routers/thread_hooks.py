"""
Thread webhook handler module for the Ordelo rider agent.
    . Processes thread lifecycle webhook events from database triggers
    . Handles thread closure for inactive conversations (background task termination)
    . Runs system message injections for a thread
    . Sends goodbye messages to users via WhatsApp
    . Implements FastAPI router endpoints for thread management
    . Triggered by Supabase cron job running job_close_thread() function
    . Provides debug endpoints for state inspection by recipient or thread_id
  Functions/Classes:
    . RunSystemMessageRequest - Input model for system message execution
    . terminate_stale_active_threads - Processes thread closure requests from scheduled job
    . run_system_message - Executes rider graph with a system message
    . debug_state_values_path - Debug endpoint to view conversation state values
    . debug_state_path - Debug endpoint to view complete conversation state
    . debug_admin_state_path - Debug endpoint to view admin conversation state
    . debug_state_by_thread_path - Debug endpoint to view state by thread_id
"""

# %%
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger
from pydantic import BaseModel

from config import client_ordelo, pg_settings
from ordelo.agents.agent_runner import (
    debug_state,
    debug_state_values,
    debug_thread,
    run_rider_agent_w_custom_msg,
)
from ordelo.agents.rider_agent import ContextSchema, builder
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


# Check if this port endpoint is still required.
@router.post(
    "/terminate-stale-active-threads",
    summary="Close inactive threads. Called by job_close_thread() PostgreSQL function via Supabase cron",
    description="""
    Processes thread closure requests from the scheduled job_close_thread() function.

    Triggered by: Ordelo endpoint /order-hooks/terminate-stale-active-threads, triggered by Supabase cron job every 5 minutes
    Source Function: job_close_thread() in ordelo_datamodels/jobs_n_functions/job_close_thread.sql

    Workflow:
    1. Receives JSON array of thread records to close
    2. For each thread:
       - Marks thread as inactive using ThreadHandler.make_threads_inactive()
       - Sends goodbye message to recipient via WhatsApp
    3. Returns success status with count of processed threads

    Payload Structure:
    [
        {
            "thread_id": "uuid",
            "recipient": "phone_number",
            "last_access_dtts": "timestamp",
            "is_active": boolean,
            "minutes_since_last_access": number
        }
    ]
    """,
)
async def terminate_stale_active_threads(
    request: Request, background_tasks: BackgroundTasks
):
    # debug_stack = await debug_state_values(recipient)

    pool = await pg_settings.get_pool()
    from utils_common.thread_management import ThreadHandler

    thread_handler = ThreadHandler(pool)

    # Fetch stale active threads
    _stale_active_threads = await thread_handler.get_stale_active_threads(5)
    for thread in _stale_active_threads:
        config = {
            "configurable": {
                "thread_id": thread["thread_id"],
                "recipient": thread["recipient"],
            }
        }
        state_values = await debug_state_values(config=config)

        # extract retain_thread from state_values
        retain_thread = state_values.get("retain_thread", False)
        thread["retain_thread"] = retain_thread  # update for logging
        if retain_thread:
            logger.info(f"Thread {thread['thread_id']} will be retained")
        else:
            background_tasks.add_task(
                run_rider_agent_w_custom_msg,
                recipient=thread["recipient"],
                config=config,
                system_msg="Call tool `terminate_conversation` with reason - Ending the conversation due to inactivity.",
            )

    return _stale_active_threads


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

    ai_response = await run_rider_agent_w_custom_msg(
        recipient=recipient,
        system_msg=request.update_message,
        state_update_dict=request.state_update_dict,
    )
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
