"""
Thread webhook handler module for the Ordelo rider agent.
    . Processes thread lifecycle webhook events from database triggers
    . Handles thread closure for inactive conversations with background webhook fan-out
    . Runs system message injections for a thread
    . Sends goodbye messages to users via WhatsApp
    . Implements FastAPI router endpoints for thread management
    . Triggered by Supabase cron job running job_close_thread() function
    . Queues restaurant webhook notifications using FastAPI background tasks
    . Provides debug endpoints for state inspection by recipient or thread_id
  Functions/Classes:
    . RunSystemMessageRequest - Input model for system message execution
    . notify_restaurant_thread_termination - Background task for stale thread webhook delivery
    . terminate_stale_active_threads - Processes thread closure requests from scheduled job
    . run_system_message - Executes rider graph with a system message
    . debug_state_values_path - Debug endpoint to view conversation state values
    . debug_state_path - Debug endpoint to view complete conversation state
    . debug_admin_state_path - Debug endpoint to view admin conversation state
    . debug_state_by_thread_path - Debug endpoint to view state by thread_id
"""

# %%
from typing import Optional
import httpx

from config.params import ONBOARDED_REST_REFS
from config import get_restaurant_webhook_url_async, logger
from fastapi import APIRouter, BackgroundTasks, HTTPException
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


async def notify_restaurant_thread_termination(rest_ref: str, webhook_url: str):
    """Deliver a stale-thread termination webhook notification in the background."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url=webhook_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error(
            f"Failed stale thread termination notification for rest_ref={rest_ref}: {exc}"
        )
    except Exception as exc:
        logger.error(
            f"Unexpected stale thread termination error for rest_ref={rest_ref}: {exc}"
        )


# Check if this port endpoint is still required.
@router.post(
    "/terminate-stale-active-threads",
    summary="Close inactive threads. Called by job_close_thread() PostgreSQL function via Supabase cron",
    description="""
    Processes thread closure requests from the scheduled job_close_thread() function.

    Triggered by: Ordelo endpoint /thread-hooks/terminate-stale-active-threads, triggered by Supabase cron job every 5 minutes
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
async def terminate_stale_active_threads(background_tasks: BackgroundTasks):
    """Trigger restaurant webhook for stale thread termination.

    Returns:
        dict with success status and queued notification count
    """
    queued_notifications = 0
    for rest_ref in ONBOARDED_REST_REFS:
        webhook_url = await get_restaurant_webhook_url_async(
            rest_ref, "terminate-stale-active-threads"
        )
        background_tasks.add_task(
            notify_restaurant_thread_termination, rest_ref, webhook_url
        )
        queued_notifications += 1

    return {"success": True, "queued_notifications": queued_notifications}


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
