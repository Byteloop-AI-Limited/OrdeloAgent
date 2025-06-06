# %%
"""
Agent runner utilities for WhatsApp automation and AI workflows.
    . Provides async utilities to run agent graphs
    . Integrates with LangGraph, LangChain messages, and PostgreSQL
    . Contains run_rider_graph for executing the rider agent's workflow
    . Contains init_ordelo_graph for initializing the rider's delivery workflow
"""

from typing import Any
from datetime import datetime
import asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from config import logger, pg_settings, _async_wa_client
from utils_common.lg_utils import get_config_for_recipient
from ordelo.agents.rider_agent import builder
from ordelo_datamodels.delivery_pymodels import DeliveryDetail
from ordelo.agent_app_handlers import create_start_job_config
from pywa.types import ButtonUrl
from langgraph.checkpoint.postgres import PostgresSaver
# %%


async def run_rider_graph(
    recipient: str, human_msg: str = None, ai_msg: str = None, system_msg: str = None
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

    # update graph state
    # Setup context
    ip_msgs = {
        "messages": [
            SystemMessage(
                "Rider has accepted the delivery job, send_start_live_tracking_link tool to send the live tracking link."
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
        },
        as_node="toolNode",
    )
    # Run Graph
    await graph.ainvoke(input=ip_msgs, config=config)
