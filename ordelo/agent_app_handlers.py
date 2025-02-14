"""
All handlers for the fastapi app that serves the Elai Ai agent
"""
# %%
import json

import uvicorn as uvicorn

from config import (
    logger,
)

from pywa_async.types import Message

from langchain_core.messages import HumanMessage, SystemMessage

from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliveryDispatch

from utils_common.lg_utils import (
    get_config_for_recipient,
)
import base64
from datetime import datetime

# %% Funcs
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"


def create_start_job_config(
    d_detail: DeliveryDetail,
    d_dispatch: DeliveryDispatch
    ) -> str:
    waypoints = [
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "restaurant",
            "desc": "restaurant",
            "rad": 10,
            "lat": d_detail.rest_lat,
            "lon": d_detail.rest_lon
        },
        {
            "_type": "waypoint",
            "tst": int(datetime.now().timestamp()),
            "rid": "customer",
            "desc": "customer",
            "rad": 10,
            "lat": d_detail.customer_lat,
            "lon": d_detail.customer_lon
        },
        ]

    start_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": True,
        "usePassword" : False,
        "monitoring": 2,
        "username": d_dispatch.rider_id,
        "deviceId": f"{d_dispatch.rider_id}-{d_detail.order_number}",
        "password": "",
        "url": "https://live-track.byteloop.ai/pub",
        "locatorDisplacement": 10,
        "locatorInterval" : 10,
        "waypoints": waypoints
    }

    # Encode config as href
    start_href = generate_config_href(start_job_config)

    return start_href

# %% Run Ordelo Graph

async def init_ordelo_graph(
    graph, pool, 
    d_detail: DeliveryDetail, 
    d_dispatch: DeliveryDispatch
    ):
    logger.info(f"Initializing Ordelo Graph with rider_id: {d_dispatch.rider_id}")
    # Setup Graph
    start_live_tracking_url = create_start_job_config(d_detail, d_dispatch)
    
    config = await get_config_for_recipient(d_dispatch.rider_id, pool)

    # update graph state

    # Setup context
    ip_msgs = {
        "messages": [
            SystemMessage("Rider has accepted the delivery job, send the live tracking link."),
            HumanMessage("I have accepted the delivery job."),
        ]
    }
    
    await graph.aupdate_state(  
        config,
        {
            "dispatch_id": d_dispatch.dispatch_id,
            "order_number": d_detail.order_number,
            "start_live_tracking_url": start_live_tracking_url
        }
    )

    await graph.ainvoke(input=ip_msgs, config=config)

async def run_ordelo_graph(msg: Message, graph, pool):
    """Executes the takeaway graph and returns the AI's response."""
    human_msg = msg.text
    recipient = msg.sender
    wa_user_name = msg.from_user.name

    config = await get_config_for_recipient(recipient, pool)

    # Check is name is captured
    state = await graph.aget_state(config=config)
    if not state.values.get(" "):
        _system_msg = f"""User Name {wa_user_name}. Address by name 
        in scenarios like first messages, When there is change in intent, user frustrated. Dont over do it.
        """
        await graph.aupdate_state(
            config,
            {"wa_user_name": wa_user_name, "messages": [SystemMessage(_system_msg)]},
            as_node="toolNode",
        )

    ip_msgs = {
        "messages": [
            HumanMessage(human_msg),
        ]
    }

    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)
    # Debug
    recent_msgs = ai_msg["messages"][-4:]
    [logger.info(msg.content) for msg in recent_msgs]

    ai_msg_content = ai_msg["messages"][-1].content

    return ai_msg_content