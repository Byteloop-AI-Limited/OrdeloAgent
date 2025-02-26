# %%
from config import project_settings
from typing import Annotated, List

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.types import Command
from typing_extensions import Literal
from langgraph.checkpoint.memory import MemorySaver
from config import _async_wa_client
from pywa.types import ButtonUrl
from langchain_core.messages import RemoveMessage

from utils_common.lg_utils import (
    create_agent_w_sys_prompt_n_tools,
    get_recipient_from_config,
    LLM_4o as llm,
    display_graph
)
# from elai.agents.respond_agent import respond_node
from ordelo.state import AgentState
from config import logger
from utils_common.wa_send.wa_senders import send_order_reciept_wa, send_catalog
from ordelo.agent_app_handlers import create_stop_job_config
from utils_common.db_utils.sbase_rest_ops import sbase_get
from ordelo_datamodels.delivery_pymodels import DeliveryDetail

from langchain_core.tools.base import InjectedToolCallId
from langchain_core.messages import ToolMessage, AIMessage



# %% DELIVERY START - send live tracking

async def send_start_live_tracking_link(
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> dict:
    """
    Generates and sends a URL for initiating live tracking on the driver's device.
    URL will be sent to rider on WhatsApp.
    
    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    recipient = get_recipient_from_config(config)

    _text="""
🚀 Get started with the delivery by cliking the below link

🔑 Remember to provide the 2-digit confirmation code after the delivery is completed!

👨‍💻 Please let me know if you have any questions during the delivery process.  
    """
    
    start_live_tracking_url = state.get('start_live_tracking_url', None) 

    if start_live_tracking_url is not None:
        # Send the URL to the rider
        await _async_wa_client.send_message(
            to=recipient,
            text=_text,
            reply_to_message_id=None,
            buttons=ButtonUrl(title="Start live tracking", url=start_live_tracking_url)
        )
        
        return Command(
            update={
                "messages": [
                    ToolMessage("Url and instructions sent to user.", tool_call_id=tool_call_id),
                    AIMessage(f"/dontRespond: {_text}")
                ]
            }
        )
    else:
        return Command(
            update={
                "messages": [
                    ToolMessage("Something went wrong. Please try again later.", tool_call_id=tool_call_id)
                ]
            }
        )

# %% DELIVERY END

async def verify_delivery_confirmation_code(
    dispatch_id: str, driver_id: str, confirmation_code: str, tool_call_id: Annotated[str, InjectedToolCallId]
) -> dict:
    """
    Verifies the 2-digit confirmation code provided by the customer upon delivery.
    
    This function validates that the provided code matches the one generated for
    this delivery and marks the delivery as completed if the code is correct.

    Args:
        dispatch_id (str): Unique identifier of the dispatched delivery job
        driver_id (str): Unique identifier of the driver completing the delivery
        confirmation_code (str): 2-digit confirmation code provided by the customer

    Returns:
        dict: A dictionary containing:
            - is_valid: Boolean indicating if the code is correct
            - delivery_status: Updated status of the delivery
            - timestamp: UTC timestamp of verification attempt
    """
    if confirmation_code == "77":
        return Command(
            update={
                "messages": [
                    ToolMessage("Confirmation code accepted. Delivery completed. Send end live tracking link (tool: `send_end_live_tracking_link`).", tool_call_id=tool_call_id)
                ]
            }
        )
    else:
        return Command(
            update={
                "messages": [
                    ToolMessage("Confirmation code is incorrect. Please try again.", tool_call_id=tool_call_id)
                ]
            }
        )

# %% DELIVERY END - send live tracking

async def send_end_live_tracking_link(
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> dict:
    """
    Sends a URL for ending live tracking on the driver's device.

    This function creates a unique URL that, when opened on the driver's phone,
    automatically stops the live tracking feature in the driver app and performs
    any necessary cleanup for the completed delivery job.

    Args:
        None

    Returns:
        dict: A dictionary containing:
            - tracking_url: URL for ending live tracking
            - expiry: UTC timestamp when the URL expires
            - cleanup_params: Dict of cleanup configuration parameters
    """
    recipient = get_recipient_from_config(config)
    stop_job_url = await create_stop_job_config()
    
    # Send the URL to the rider
    await _async_wa_client.send_message(
            to=recipient,
            text="Thank you, delivery is complete. Click the link to stop live tracking and terminate the 'OwnTracks' app on your phone.",
            reply_to_message_id=None,
            buttons=ButtonUrl(title="Stop live tracking", url=stop_job_url)
        )

    return Command(
            update={
                "messages": [
                    ToolMessage("Link to stop tracking sent.", tool_call_id=tool_call_id),
                    AIMessage(f"/dontRespond: Link to stop tracking sent.")
                ]
            }
        )

    

# %% Create Agent
with open(f"{project_settings.project_root}/ordelo/agents/rider_agent.md", "r") as file:
    rider_agent_prompt = file.read()


# %%
_rider_agent_tools = [
    send_start_live_tracking_link,
    verify_delivery_confirmation_code,
    send_end_live_tracking_link,
]

rider_agent_tools = [ tool(service) for service in _rider_agent_tools ]

rider_agent = create_agent_w_sys_prompt_n_tools(
    llm=llm, 
    tools=rider_agent_tools, 
    system_prompt=rider_agent_prompt
    )

# %% rider_agent_node
def agent_node(state: AgentState) -> Command[Literal["toolNode", "respondNode", END]]:

    # If tool message replied to user already, end the turn
    if isinstance(state["messages"][-1], AIMessage):
        return Command(
            goto=END
        )

    # Else Invoke rider agent
    ai_msg = rider_agent.invoke(state)
    if ai_msg.tool_calls:
        goto = "toolNode"
    else:
        goto = "respondNode"

    return Command(
        update={"messages": [ai_msg]},
        goto=goto,
    )


async def respond_node(
    state: AgentState,
    config: RunnableConfig
) -> Command[Literal[END]]:
    """
    Main agent node that processes user input and determines next action
    """
    if config['configurable']['recipient']:
        recipient = config['configurable']['recipient']
    else:
        # raise error
        raise ValueError("No recipient provided")

    last_ai_msg = state["messages"][-1]

    await _async_wa_client.send_message(
            to=recipient,
            text=last_ai_msg.content
        )
    return Command(
            goto=END, update={"messages": [last_ai_msg]}
        )
        



# %% Construct the graph

builder = StateGraph(AgentState)
builder.add_node("riderAgent", agent_node)
builder.add_node("respondNode", respond_node)
builder.add_node("toolNode", ToolNode(rider_agent_tools))
builder.add_edge(START, "riderAgent")
builder.add_edge("toolNode", "riderAgent")


""" Test
# %% Memory and config
memory = MemorySaver()
graph = builder.compile(checkpointer=memory)
display_graph(graph)

config = {
    "configurable": {
        "thread_id": 24,
        "recipient": "447448440754"
    }
}
graph.update_state(
    config,
    {
            "dispatch_id": 123,
            "order_number": 123,
            "start_live_tracking_url": "https://google.com"
        },
)
# %%
ip_msgs = {
    "messages": [
        SystemMessage("rider has accepted the delivery job, send the live tracking link. {{'dispatch_id':'40'}}"),
        HumanMessage("I have accepted the delivery job.")
    ]
}

ai_msg = await graph.ainvoke(ip_msgs, config=config)
ai_msg
# %%
state = graph.get_state(config)

# %%
"""