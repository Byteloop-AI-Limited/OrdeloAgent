"""
Core agent runner for Ordelo's delivery workflow system
    . Dependencies: LangGraph, LangChain, psycopg_pool, WhatsApp client
    . Initializes and runs LangGraph-based agent workflows
    . Processes messages between rider agents and WhatsApp interface
    . Manages delivery job state through PostgreSQL persistence
    . Coordinates with rider_agent for workflow execution
  Functions/Classes:
    . run_rider_graph - Executes rider graph and returns AI response
    . init_ordelo_graph - Initializes delivery workflow for given detail
"""

from typing import Any
from datetime import datetime
import asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from config import logger, pg_settings, _async_wa_client, client_ordelo
from utils_common.lg_utils import get_config_for_recipient
from ordelo.agents.rider_agent import builder
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from ordelo.agent_app_handlers import create_start_job_config
from pywa.types import ButtonUrl
from langgraph.checkpoint.postgres import PostgresSaver
# %%


async def run_rider_graph(
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

    # Run the graph with pool
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    config: dict[str, Any] = await get_config_for_recipient(recipient, pool)
    if state_update_dict:
        await graph.aupdate_state(config, state_update_dict, as_node="toolNode")
    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)
    ai_msg_content: str = ai_msg["messages"][-1].content

    return ai_msg_content


# %% Init Ordelo graph
async def init_ordelo_graph(d_detail: DeliveryDetail):
    # Setup Graph
    pool: AsyncConnectionPool = await pg_settings.get_pool()
    checkpointer: AsyncPostgresSaver = AsyncPostgresSaver(pool)
    graph = builder.compile(checkpointer=checkpointer)
    config = await get_config_for_recipient(d_detail.rider_id, pool)

    start_live_tracking_url = await create_start_job_config(d_detail)
    # using client.table, query the rider_master table on rider_id and get the name.
    rider_name = (
        client_ordelo.table("rider_master")
        .select("rider_name")
        .eq("rider_id", d_detail.rider_id)
        .execute()
        .data[0]["rider_name"]
    )
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
            "dispatch_id": d_detail.dispatch_id,
            "order_number": d_detail.order_number,
            "start_live_tracking_url": start_live_tracking_url,
            "delivery_start_dtts": delivery_start_dtts,
            "rider_name": rider_name,
        },
        as_node="toolNode",
    )
    # Run Graph
    await graph.ainvoke(input=ip_msgs, config=config)
