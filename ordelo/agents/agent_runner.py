"""
Core agent runner for Ordelo's delivery workflow system
    . Dependencies: LangGraph, LangChain, psycopg_pool, WhatsApp client
    . Initializes and runs LangGraph-based agent workflows
    . Processes messages between rider agents and WhatsApp interface
    . Manages delivery job state through PostgreSQL persistence
    . Coordinates with rider_agent for workflow execution
    . Seeds pickup_time into graph state at init for adjusted-pickup-time notifications
    . Supports refreshing graph state via state_update_dict (e.g. updated pickup_time on adjust)
    . Retries only initial thread acquisition on transient PostgreSQL connection loss
    . Exposes a cheap post-pickup guard so callers can skip agent runs for pre-pickup-only updates
      (superseded -- see below)
  Functions/Classes:
    . _get_config_for_recipient_with_retry - Reconciles one uncertain thread acquisition
    . is_food_already_picked_up - Reads is_restaurant_confirmation_code_verified via get_latest_state RPC.
      Superseded by ordelo.delivery_progress.check_delivery_progress, which reads delivery_inflight /
      delivery_dispatch instead and stays readable after a thread closes or is deleted; this function
      currently has no callers. Kept as the one worked Python example of calling get_latest_state --
      see docs/get_latest_state_guide.md for the RPC itself.
    . run_rider_agent_w_custom_msg - Executes rider graph with custom messages and returns AI response
    . clear_wa_location_request - Clears a stale wa_location request id from graph state after a failed prompt
    . clear_pickup_alert_cue - Disarms a spent pickup-alert cue so it cannot re-fire on a later turn
    . init_ordelo_graph - Initializes delivery workflow for given detail
    . debug_state - Returns shortened graph state for debugging
    . debug_state_values - Returns state values for debugging
    . job_end_stale_conversations - Closes stale active threads
    . run_rider_agent_repl - Async console REPL for local testing

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . get_latest_state (function, ordelo_datamodels/agent_threads/get_latest_state.sql): calls, calls (name passed to a helper)
  . thread (table, restaurant-agents): reads, named in code (passed to a query helper)
(end of database objects)
"""

# %%

import asyncio
from datetime import datetime
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import OperationalError
from psycopg_pool import AsyncConnectionPool

from config import logger, pg_settings, project_settings, _async_wa_client, client_ordelo
from utils_common.lg_utils import get_config_for_recipient
from ordelo.agents.rider_agent import builder, ContextSchema

# from ordelo.agents.byteloop_agent import graph as bloop_agent
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from utils_common.lg_utils import (
    get_state_values,
    shorten_state_messages,
)
# %%

# pool: AsyncConnectionPool = await pg_settings.get_pool()
# recipient = msg.sender
# thread_handler = ThreadHandler(pool)

# %%


# %%


_THREAD_ACQUISITION_ATTEMPTS = 2
_THREAD_ACQUISITION_RETRY_DELAY_SECONDS = 0.5


async def _get_config_for_recipient_with_retry(
    recipient: str, pool: AsyncConnectionPool
) -> tuple[dict, bool]:
    """Acquire or reconcile a rider thread after one connection failure.

    The retry boundary intentionally contains only ``get_config_for_recipient``.
    Graph state updates, graph invocation, tools, and external messages must stay
    outside this helper so they are never replayed by this recovery path.
    """
    for attempt in range(1, _THREAD_ACQUISITION_ATTEMPTS + 1):
        try:
            return await get_config_for_recipient(recipient, pool)
        except OperationalError:
            if attempt >= _THREAD_ACQUISITION_ATTEMPTS:
                logger.error(
                    f"Thread acquisition failed after {attempt} attempts "
                    f"for recipient={recipient}"
                )
                raise

            logger.warning(
                f"Thread acquisition connection failure for recipient={recipient} "
                f"(attempt {attempt}/{_THREAD_ACQUISITION_ATTEMPTS}); retrying once"
            )
            await asyncio.sleep(_THREAD_ACQUISITION_RETRY_DELAY_SECONDS)

    raise RuntimeError("Thread acquisition retry loop exited unexpectedly")


# %% Post-pickup guard
PICKED_UP_STATE_KEY = "is_restaurant_confirmation_code_verified"


async def is_food_already_picked_up(recipient: str) -> bool:
    """Reports whether the rider has already collected the food from the restaurant.

    Reads ``is_restaurant_confirmation_code_verified`` straight off the latest
    persisted checkpoint via the ``get_latest_state`` SQL function, so callers can
    suppress pre-pickup-only notifications (food ready, pickup time adjusted)
    without compiling the graph or spending an LLM turn.

    Returns False when there is no active thread, no checkpoint, or the read
    fails, so a transient DB problem degrades to the previous behaviour rather
    than silently swallowing a rider notification.

    Superseded (no current callers): ``get_latest_state`` only resolves threads
    with ``is_active IS TRUE``, so once a thread is closed or deleted (delivery
    completed, thread terminated as stale) this silently returns False --
    indistinguishable from "not yet picked up". ``ordelo.delivery_progress.check_delivery_progress``
    reads ``delivery_inflight`` / ``delivery_dispatch`` instead and stays correct
    post-completion. Kept as a worked example of calling ``get_latest_state`` from
    Python; see ``docs/get_latest_state_guide.md`` for the RPC itself.
    """
    try:
        response = await asyncio.to_thread(
            lambda: client_ordelo.rpc(
                "get_latest_state",
                {
                    "p_recipient": recipient,
                    "p_agent": project_settings.rest_ref,
                    "p_state_key": PICKED_UP_STATE_KEY,
                },
            ).execute()
        )
    except Exception as e:
        logger.error(
            f"Failed to read {PICKED_UP_STATE_KEY} for recipient={recipient}: {e}"
        )
        return False

    return response.data is True


async def run_rider_agent_w_custom_msg(
    recipient: str,
    human_msg: str = None,
    ai_msg: str = None,
    system_msg: str = None,
    state_update_dict: dict = None,
):
    """Runs the rider graph and returns the AI's response."""
    logger.debug(
        f"executing run_rider_graph with human_msg: {human_msg}, recipient: {recipient}"
    )

    # whichever msg is not None, for a list of msgs.
    msgs: list[SystemMessage | AIMessage | HumanMessage] = []
    if system_msg:
        msgs.append(SystemMessage(system_msg))
    if ai_msg:
        msgs.append(AIMessage(ai_msg))
    if human_msg:
        msgs.append(HumanMessage(human_msg))

    ip_msgs: dict[str, list[SystemMessage | AIMessage | HumanMessage]] = {
        "messages": msgs
    }

    # Build ctx
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)

    context_schema = ContextSchema(
        pool=pool,
        wa_client=_async_wa_client,
        recipient=recipient,
        client_ordelo=client_ordelo,
    )

    # Run the graph with pool
    graph = builder.compile(checkpointer=checkpointer)
    config, is_new_thread = await get_config_for_recipient(recipient, pool)
    if state_update_dict:
        await graph.aupdate_state(config, state_update_dict, as_node="toolNode")
    ai_msg = await graph.ainvoke(input=ip_msgs, config=config, context=context_schema)
    ai_msg_content: str = ai_msg["messages"][-1].content

    return ai_msg_content


# %% Clear a stale wa_location request from graph state
async def clear_wa_location_request(recipient: str) -> None:
    """Clears wa_location_request_id/force_wa_location_prompt after a failed prompt attempt.

    Prevents a later, unrelated turn from firing the location tool against a
    request that was already marked failed.
    """
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    config, _ = await get_config_for_recipient(recipient, pool)
    await graph.aupdate_state(
        config,
        {"wa_location_request_id": None, "force_wa_location_prompt": False},
        as_node="toolNode",
    )


# %% Clear a spent pickup-alert cue from graph state
async def clear_pickup_alert_cue(recipient: str) -> None:
    """Disarms pickup_alert_offset/pickup_alert_phase after an alert run.

    The cue is written by aupdate_state *before* the graph is invoked, and
    notify_pickup_reminder only clears it if it actually runs. If the LLM answers
    with text instead of calling the tool -- or the tool raises and ToolNode
    swallows it -- the offset stays in state and the tool's own guard then
    *permits* the call on any later, unrelated rider turn, producing a bogus
    "you're N min past pickup" hours later.

    The cue is single-use by definition, so callers disarm it unconditionally once
    the run is over. Mirrors clear_wa_location_request.
    """
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    config, _ = await get_config_for_recipient(recipient, pool)
    await graph.aupdate_state(
        config,
        {"pickup_alert_offset": None, "pickup_alert_phase": None},
        as_node="toolNode",
    )


# %% Init Ordelo graph
async def init_ordelo_graph(
    delivery_summary: DeliverySummary, rider_id: str, rider_name: str, dispatch_id: int
):
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    config, _ = await _get_config_for_recipient_with_retry(rider_id, pool)

    context_schema = ContextSchema(
        pool=pool,
        wa_client=_async_wa_client,
        recipient=rider_id,
        client_ordelo=client_ordelo,
    )

    # Setup Graph
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    # update graph state
    # Setup context
    ip_msgs = {
        "messages": [
            SystemMessage(
                f"Rider {rider_name} has accepted the delivery job, call `send_delivery_instructions` tool to send the delivery instructions"
            ),
            HumanMessage("I have accepted the delivery job."),
        ]
    }
    delivery_start_dtts = datetime.now().isoformat()
    await graph.aupdate_state(
        config,
        {
            "dispatch_id": dispatch_id,
            "order_number": delivery_summary.order_number,
            "delivery_start_dtts": delivery_start_dtts,
            "rider_name": rider_name,
            "pickup_time": delivery_summary.pickup_time,
            "pickup_alert_offset": None,
            "pickup_alert_phase": None,
        },
        as_node="toolNode",
    )
    # Run Graph
    await graph.ainvoke(input=ip_msgs, config=config, context=context_schema)


# %%
# %% Debug State
async def debug_state(recipient: str, full_state: bool = False) -> dict:
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    config, _ = await get_config_for_recipient(recipient, pool)
    state = await graph.aget_state(config=config)

    if full_state:
        debug_stack = {
            **get_state_values(state.values),
            "messages": shorten_state_messages(state.values["messages"]),
        }
    else:
        debug_stack = {
            **get_state_values(state.values),
            "messages": shorten_state_messages(state.values["messages"]),
        }
    return debug_stack


# %% Debug State
async def debug_state_values(
    recipient: Optional[str] = None, config: Optional[dict] = None
) -> dict:
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)

    if config is None:
        config, _ = await get_config_for_recipient(recipient, pool)
    state = await graph.aget_state(config=config)

    state_values = get_state_values(state.values)
    return state_values


# %% Debug by thread


async def debug_thread(thread_id: str, full_state: bool = False) -> dict:
    """Debug state by thread_id - fetches recipient from thread table."""
    from config import client_ordelo

    result = (
        client_ordelo.table("thread")
        .select("thread_id", "recipient")
        .eq("thread_id", thread_id)
        .execute()
    )

    if not result.data:
        raise ValueError(f"Thread not found: {thread_id}")
    recipient = result.data[0]["recipient"]
    config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}
    # Get graph and then state
    pool = await pg_settings.get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    state = await graph.aget_state(config=config)

    if full_state:
        debug_stack = state.values
    else:
        debug_stack = {
            **get_state_values(state.values),
            "messages": shorten_state_messages(state.values["messages"]),
        }
    return debug_stack


# %%
async def job_end_stale_conversations(
    thread_handler=None,
    stale_minutes: int = 5,
):
    from config import pg_settings
    from utils_common.thread_management.thread_handler import ThreadHandler

    if thread_handler is None:
        pool: AsyncConnectionPool = await pg_settings.get_pool()
        thread_handler = ThreadHandler(pool)

    # Fetch stale active threads
    op = await thread_handler.get_stale_active_threads(stale_minutes)

    for row in op:
        config = {
            "configurable": {
                "thread_id": row["thread_id"],
                "recipient": row["recipient"],
            }
        }
        logger.info(f"Closing stale thread: {row}")
        # await run_elai_graph_with_custom_msg(
        #     recipient=row["recipient"],
        #     human_msg="get me out of here",
        #     config=config,
        # )


# %% Async REPL for local testing
async def run_rider_agent_repl(recipient: str) -> None:
    """Interactive loop: send console input to the rider graph until 'exit'."""
    while True:
        user_input = input("Human Input: ")
        if user_input == "exit":
            break

        print("====================")
        ai_response = await run_rider_agent_w_custom_msg(
            recipient=recipient,
            human_msg=user_input,
        )
        print(ai_response)


# %% This doesnt work.
# await run_rider_agent_repl('447448440754')


# %% get state values
# await debug_state('447469849539')
# await debug_thread('ORDELO-ee723178-5eb3-4d6b-a171-1f7c2d1e80e2')
# %%
"""
from config import client_ordelo
from ordelo_datamodels.delivery_pymodels import DeliverySummary

order_number = "ELAS-OOLX-24"

res = client_ordelo.table("delivery_summary").select("*").eq("order_number", order_number).execute()

delivery_summary = DeliverySummary(**res.data[0])
rider_id='447448440754'
rider_name='Rider Name'
dispatch_id=76
    
# %%

pool: AsyncConnectionPool = await pg_settings.get_pool()
# recipient = d_detail.rider_id

context_schema = ContextSchema(
    pool=pool,
    wa_client=_async_wa_client,
    recipient=rider_id,
    client_ordelo=client_ordelo,
)

# Setup Graph
checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
graph = builder.compile(checkpointer=checkpointer)
config, _ = await get_config_for_recipient(rider_id, pool)

start_live_tracking_url = "dummy_url"

# update graph state
# Setup context
ip_msgs = {
    "messages": [
        SystemMessage(
            f"Rider {rider_name} has accepted the delivery job, call `send_delivery_instructions` tool to send the delivery instructions"
        ),
        HumanMessage("I have accepted the delivery job."),
    ]
}
delivery_start_dtts = datetime.now().isoformat()
await graph.aupdate_state(
    config,
    {
        "dispatch_id": dispatch_id,
        "order_number": delivery_summary.order_number,
        "start_live_tracking_url": start_live_tracking_url,
        "delivery_start_dtts": delivery_start_dtts,
        "rider_name": rider_name,
    },
    as_node="toolNode",
)
# Run Graph
await graph.ainvoke(input=ip_msgs, config=config, context=context_schema)
"""
