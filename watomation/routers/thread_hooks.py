"""
Thread webhook handler module for Elai Agent
    . Processes thread lifecycle webhook events from database triggers
    . Handles thread closure for inactive conversations (background task termination)
    . Sends goodbye messages to users via WhatsApp
    . Implements FastAPI router endpoints for thread management
    . Triggered by Supabase cron job running job_close_thread() function
    . Provides debug endpoints for state inspection by recipient or thread_id
  Functions/Classes:
    . close_threads - Processes thread closure requests from scheduled job
    . debug_state_values_path - Debug endpoint to view conversation state values
    . debug_state_path - Debug endpoint to view complete conversation state
    . debug_admin_state_path - Debug endpoint to view admin conversation state
    . debug_state_by_thread_path - Debug endpoint to view state by thread_id
"""

# %%
from fastapi import APIRouter, BackgroundTasks, Request
from config import pg_settings, client_ordelo
from loguru import logger
from typing import Optional
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from ordelo.agents.rider_agent import builder, ContextSchema
from utils_common.lg_utils import (
    get_state_values,
    shorten_state_messages,
)
from ordelo.agents.agent_runner import (
    run_rider_agent_w_custom_msg,
    debug_state_values,
    debug_state,
)
# %% Define Dependencies and routes

router = APIRouter(tags=["thread-hooks"])


# %%
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


@router.get("/debug-state-values")
async def debug_state_values_path(recipient: Optional[str] = "447448440754"):
    debug_stack = await debug_state_values(recipient)
    return debug_stack


@router.get("/debug-state")
async def debug_state_path(recipient: Optional[str] = "447448440754"):
    debug_stack = await debug_state(recipient)
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
