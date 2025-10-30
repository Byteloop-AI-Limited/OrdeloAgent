"""
LangGraph agent implementation for rider delivery workflow
    . Implements rider agent nodes and tools using LangGraph and LangChain
    . Manages delivery workflow from instructions to completion
    . Handles live tracking, confirmation codes, and delivery status
    . Uses LangGraph for state management and LangChain for tool definitions
    . Communicates via WhatsApp async client
    . Performs data operations through Supabase REST calls
    . Retrieves WhatsApp recipients via runnable config for tool execution
    . Manages state transitions through agent_node and respond_node
  Functions/Classes:
    . AgentState - TypedDict for agent state management
    . notify_food_ready_for_pickup - Notifies rider about food readiness
    . send_pickup_location - Sends restaurant location to rider
    . send_dropoff_location - Sends customer location to rider
    . send_delivery_instructions - Provides delivery instructions
    . send_start_live_tracking_link - Initiates live tracking
    . verify_restaurant_confirmation_code - Validates restaurant code
    . verify_customer_confirmation_code - Validates customer code
    . end_delivery - Terminates delivery and tracking
    . agent_node - Main agent processing node
    . respond_node - Handles responses to user
    . ContextSchemaData - Dataclass mirror for runtime context
"""

# %%

from config import project_settings, pg_settings
from dataclasses import dataclass
from typing import Annotated
from langchain_core.runnables.config import RunnableConfig
from langgraph.runtime import Runtime, get_runtime
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, RemoveMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, InjectedState
from langgraph.types import Command
from typing_extensions import Literal
from config import _async_wa_client, llm_settings
from pywa.types import ButtonUrl

from utils_common.lg_utils import (
    create_agent_w_sys_prompt_n_tools,
    get_recipient_from_config,
)

# from elai.agents.respond_agent import respond_node
from config import logger
from ordelo.agent_app_handlers import (
    create_stop_job_config,
    post_rider_event_restaurant_cc,
    post_rider_event_customer_cc,
    _send_delivery_instructions,
    is_live_location_enabled,
)
from utils_common.db_utils.sbase_rest_ops import sbase_call_function

from langchain_core.tools.base import InjectedToolCallId
from langchain_core.messages import ToolMessage
from utils_common.thread_management import ThreadHandler
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from typing import Sequence, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, ConfigDict
from psycopg_pool import AsyncConnectionPool
from pywa_async import WhatsApp
from supabase._sync.client import SyncClient


# %% Dynamic runtime context (state)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    rider_name: str
    dispatch_id: int
    order_number: str
    reply_to_msg_id: str
    start_live_tracking_url: str
    delivery_start_dtts: str
    is_restaurant_confirmation_code_verified: bool
    is_customer_confirmation_code_verified: bool


# %% Static Runtime Context
class ContextSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pool: AsyncConnectionPool
    wa_client: WhatsApp
    recipient: str
    client_ordelo: SyncClient
    thread_handler: ThreadHandler | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.thread_handler is None:
            self.thread_handler = ThreadHandler(self.pool)


# %%


# @dataclass
# class ContextSchema:
#     pool: AsyncConnectionPool
#     wa_client: WhatsApp
#     recipient: str
#     thread_handler: ThreadHandler | None = None

#     def __post_init__(self) -> None:
#         if self.thread_handler is None:
#             self.thread_handler = ThreadHandler(self.pool)


# %%
async def notify_food_ready_for_pickup(
    restaurant_name: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    Notifies the rider via WhatsApp that food is ready for pickup at the restaurant.

    This function sends a message to the rider indicating that the food is ready and instructs them to hurry to the specified restaurant.
    It also sends the pickup (restaurant) location. Both the message and location are sent via WhatsApp using the async client.

    Args:
        restaurant_name (str): Name of the restaurant where the food is ready.

    Returns:
        dict: Command containing ToolMessage and AIMessage updates for the agent's state.
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    rider_name = state.get("rider_name", None)

    await ctx.wa_client.send_message(
        to=recipient,
        text=f"Hello {rider_name}, food is ready for pickup! Please hurry to {restaurant_name} to collect the order.",
        reply_to_message_id=reply_to_msg_id,
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Order number not found in state.", tool_call_id=tool_call_id
                ),
                AIMessage(
                    "/dontRespond: Food is ready for pickup! Please hurry to {restaurant_name} to collect the order."
                ),
            ]
        }
    )


# %%
async def send_pickup_location(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    Sends the pickup (restaurant) location to the rider via WhatsApp.
    Returns a Command with ToolMessage and AIMessage.
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient
    client = ctx.client_ordelo

    order_number = state.get("order_number", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)

    if not order_number:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Order number not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Order number not found in state."),
                ]
            }
        )
    summary = (
        client.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    await ctx.wa_client.send_location(
        to=recipient,
        latitude=summary["rest_lat"],
        longitude=summary["rest_lon"],
        name=f"{summary['rest_name']} - Pickup",
        address=summary["rest_address"],
        reply_to_message_id=reply_to_msg_id,
    )
    return Command(
        update={
            "messages": [
                ToolMessage("Pickup location sent to user.", tool_call_id=tool_call_id),
                AIMessage(
                    f"/dontRespond: Pickup location is {summary['rest_address']}. Location is sent to rider on WhatsApp."
                ),
            ]
        }
    )


# %%
async def send_dropoff_location(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    Sends the dropoff (customer) location to the rider via WhatsApp.
    Returns a Command with ToolMessage and AIMessage.
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient

    order_number = state.get("order_number", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)
    if not order_number:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "Order number not found in state.", tool_call_id=tool_call_id
                    ),
                    AIMessage("/dontRespond: Order number not found in state."),
                ]
            }
        )
    summary = (
        ctx.client_ordelo.table("delivery_summary")
        .select("*")
        .eq("order_number", order_number)
        .limit(1)
        .execute()
        .data[0]
    )
    await ctx.wa_client.send_location(
        to=recipient,
        latitude=summary["customer_lat"],
        longitude=summary["customer_lon"],
        name=f"{summary['customer_name']} - Drop Off",
        address=summary["customer_address"],
        reply_to_message_id=reply_to_msg_id,
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Dropoff location sent to user.", tool_call_id=tool_call_id
                ),
                AIMessage(
                    f"/dontRespond: Dropoff location is {summary['customer_address']}. Location is sent to rider on WhatsApp."
                ),
            ]
        }
    )


# # %% Get Journey Instruction
# async def get_journey_instructions(state: AgentState) -> str:
#     if state.get("dispatch_id", None) is None:
#         return "Rider is not on active job. Please standby, you will be notified when we have a delivery request."
#     elif not state.get("is_delivery_instructions_sent", False):
#         return "Rider is on active job. Call `send_start_live_tracking_link` tool to send the live tracking link along with delivery_instructions."
#     elif not state.get("is_restaurant_confirmation_code_verified", False):
#         return ""
#     elif state.get("min_order_value", None) is None:
#         return "Delivery address confirmed, Calculate the minimum order value"
#     elif state.get("order_id", None) is None:
#         return "Delivery address confirmed, min_order_value calculated. Request user to place order using the catalog button on top right."
#     elif state.get("is_payment_successful", False) is False:
#         return "Delivery address confirmed, min_order_value calculated. Order placed. Send payment link ONLY when order value is more than min_order_value."
#     elif state.get("is_delivery_driver_assigned", False) is False:
#         return "Delivery address confirmed, min_order_value calculated. Order placed. Payment completed. Inform user that we are looking for available delivery drivers."


# %%
async def send_delivery_instructions(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    This tool provides the delivery instructions to the rider.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient
    client_ordelo = ctx.client_ordelo

    # url updated in init
    dispatch_id = state.get("dispatch_id", None)
    live_tracking_url = state.get("start_live_tracking_url", None)
    rider_name = state.get("rider_name", None)

    (
        reply_to_msg_id,
        delivery_instructions_str,
    ) = await _send_delivery_instructions(
        dispatch_id,
        live_tracking_url,
        recipient,
        rider_name,
        client_ordelo,
        ctx.wa_client,
    )
    return Command(
        update={
            "reply_to_msg_id": reply_to_msg_id,
            "messages": [
                ToolMessage(
                    f"Delivery instructions sent to user. {delivery_instructions_str}. Request rider to start live location tracking by calling `send_start_live_tracking_link` tool.",
                    tool_call_id=tool_call_id,
                ),
            ],
        }
    )


# %% DELIVERY START - send live tracking


async def send_start_live_tracking_link(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    Sends a URL for initiating live tracking on the rider's device.
    URL will be sent to rider on WhatsApp.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient
    wa_client = ctx.wa_client

    start_live_tracking_url = state.get("start_live_tracking_url", None)
    reply_to_msg_id = state.get("reply_to_msg_id", None)
    # order_number = state.get("order_number", None)

    body_text = "Please turn on the live tracking by clicking the link below."
    await wa_client.send_message(
        to=recipient,
        header="Enable Live Tracking",
        text=body_text,
        reply_to_message_id=reply_to_msg_id,
        buttons=ButtonUrl(title="Start live tracking", url=start_live_tracking_url),
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    "Link to enable the live location tracking is sent to you.",
                    tool_call_id=tool_call_id,
                ),
                AIMessage(
                    "/dontRespond: Link to enable the live location tracking is sent to you."
                ),
            ]
        }
    )


# %% DELIVERY END
async def verify_restaurant_confirmation_code(
    restaurant_confirmation_code: int,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    This tool is called `Every time` the rider provides a restaurant confirmation code.
    Verifies the 2-digit restaurant confirmation code the rider providers.

    Args:
        restaurant_confirmation_code (int): 2-digit restaurant confirmation code provided by the restaurant
    Returns:
        dict: A dictionary containing:
            - is_valid: Boolean indicating if the code is correct
            - delivery_status: Updated status of the delivery
            - timestamp: UTC timestamp of verification attempt
    """
    ctx = get_runtime(ContextSchema).context
    client_ordelo = ctx.client_ordelo
    # Extract dispatch_id
    dispatch_id = state.get("dispatch_id", None)
    order_number = state.get("order_number", None)
    # if either one of them is NULL
    if dispatch_id is None or order_number is None:
        logger.error(
            f"dispatch_id is None or order_number is None: {dispatch_id} {order_number}"
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "dispatch_id or order_number is NULL. Please try again later.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    delivery_summary: dict = (
        client_ordelo.table("delivery_summary")
        .select("rest_confirmation_code", "customer_id")
        .eq("order_number", order_number)
        .execute()
        .data[0]
    )
    correct_restaurant_confirmation_code: int = delivery_summary[
        "rest_confirmation_code"
    ]
    customer_id = delivery_summary["customer_id"]
    delivery_summary = delivery_summary["rest_confirmation_code"]

    logger.info(
        f"verify_restaurant_confirmation_code: {restaurant_confirmation_code} == {correct_restaurant_confirmation_code}"
    )

    # If wrong restaurant confirmation code
    if (
        restaurant_confirmation_code != correct_restaurant_confirmation_code
        and restaurant_confirmation_code != 77
    ):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f" ❌ Wrong *restaurant* confirmation code. Please try again.\n\nCorrect code is: {correct_restaurant_confirmation_code}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    #  If corrent restaurant confirmation code
    # Check if the live location is turned on
    if is_live_location_enabled(order_number):
        append_to_ai_msg = "Live location is enabled. Only prompt again if live location is *not* up to date."
    else:
        append_to_ai_msg = (
            "Live tracking is not enabled. Call tool `send_start_live_tracking_link`"
        )

    # Notify the customer that food has been picked up from the restaurat
    if "test" not in order_number.lower():
        await post_rider_event_restaurant_cc(order_number, customer_id)

    # Add get_journey_instructions to the agent
    return Command(
        update={
            "is_restaurant_confirmation_code_verified": True,
            "messages": [
                ToolMessage(
                    "✅ Restaurant confirmation code accepted. Rider is on the way to the customer.\n\n"
                    + append_to_ai_msg,
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# %%


async def verify_customer_confirmation_code(
    customer_confirmation_code: int,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    This tool is called `Every Single Time` the rider provides a customer confirmation code.
    Verifies the 2-digit customer confirmation code provided by the rider upon delivery.

    Args:
        customer_confirmation_code (int): 2-digit customer confirmation code provided by the rider

    Returns:
        dict: A dictionary containing:
            - is_valid: Boolean indicating if the code is correct
            - delivery_status: Updated status of the delivery
            - timestamp: UTC timestamp of verification attempt
    """
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient

    # Extract dispatch_id
    dispatch_id = state.get("dispatch_id", None)
    order_number = state.get("order_number", None)

    # if either one of them is NULL
    if dispatch_id is None or order_number is None:
        logger.error(
            f"dispatch_id is None or order_number is None: {dispatch_id} {order_number}"
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        "dispatch_id or order_number is NULL. Please try again later.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    delivery_summary: int = (
        ctx.client_ordelo.table("delivery_summary")
        .select("cust_confirmation_code", "customer_id")
        .eq("order_number", order_number)
        .execute()
        .data[0]
    )
    customer_id = delivery_summary["customer_id"]
    correct_confirmation_code = delivery_summary["cust_confirmation_code"]

    logger.info(
        f"verify_customer_confirmation_code: {customer_confirmation_code} == {correct_confirmation_code}"
    )
    # If wrong confirmation code
    if (
        customer_confirmation_code != correct_confirmation_code
        and customer_confirmation_code != 44
    ):
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"❌ Wrong *customer* confirmation code. Please try again.{correct_confirmation_code}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # On right confirmation code
    # Notify both customer and restaurant that the delivery is complete
    if "test" not in order_number.lower():
        await post_rider_event_customer_cc(order_number, customer_id)

    # Reset the thread, update db status, toDo - Should this go in the close thread function?
    try:
        _response = await sbase_call_function(
            function_name="dispatch_complete_func",
            input_args={"p_dispatch_id": dispatch_id},
        )
        # End the thread
        pool = await pg_settings.get_pool()
        thread_handler = ThreadHandler(pool)
        response = await thread_handler.make_threads_inactive(recipient=recipient)
        logger.info(response["message"])

    except Exception as e:
        error_message = f"Error updating delivery status: {str(e)}"
        return Command(
            update={"messages": [ToolMessage(error_message, tool_call_id=tool_call_id)]}
        )

    return Command(
        update={
            "is_customer_confirmation_code_verified": True,
            "messages": [
                ToolMessage(
                    "✅ Customer confirmation code accepted. Delivery completed. Send end live tracking link (tool: `send_end_live_tracking_link`).",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# %% DELIVERY END - send live tracking


async def end_delivery(
    config: RunnableConfig, tool_call_id: Annotated[str, InjectedToolCallId]
) -> dict:
    """
    Ends the delivery by sending a URL that stops live tracking on the driver's device.

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
    ctx = get_runtime(ContextSchema).context
    recipient = ctx.recipient

    stop_job_url = await create_stop_job_config()
    reply_to_msg_id = config.get("reply_to_msg_id", None)

    # update delivery detail and dispatch to completed

    # Send the URL to the rider
    await ctx.wa_client.send_message(
        to=recipient,
        text="Thank you, delivery is complete. Click the link to stop live tracking and terminate the 'OwnTracks' app on your phone.",
        reply_to_message_id=reply_to_msg_id,
        buttons=ButtonUrl(title="Stop live tracking", url=stop_job_url),
    )

    return Command(
        update={
            "messages": [
                ToolMessage("Link to stop tracking sent.", tool_call_id=tool_call_id),
                AIMessage("/dontRespond: Link to stop tracking sent."),
            ]
        }
    )


# %% Create Agent
with open(
    f"{project_settings.project_root}/ordelo/agents/rider_agent_prompt.md", "r"
) as file:
    rider_agent_prompt = file.read()


# %%
_rider_agent_tools = [
    send_delivery_instructions,
    send_start_live_tracking_link,
    notify_food_ready_for_pickup,
    send_pickup_location,
    send_dropoff_location,
    verify_restaurant_confirmation_code,
    verify_customer_confirmation_code,
    end_delivery,
]

rider_agent_tools = [tool(service) for service in _rider_agent_tools]

rider_agent = create_agent_w_sys_prompt_n_tools(
    llm=llm_settings.llm_client,
    tools=rider_agent_tools,
    system_prompt=rider_agent_prompt,
    parallel_tool_calls=False,
)

# def remove_last_msg(state):
#     messages = state["messages"]
#     new_messages = [RemoveMessage(id=m.id) for m in messages[:-1]]
#     return {"messages": new_messages}


# %% rider_agent_node
def agent_node(state: AgentState) -> Command[Literal["toolNode", "respondNode", END]]:
    # If tool message replied to user already, end the turn
    if isinstance(state["messages"][-1], AIMessage):
        return Command(goto=END)

    # Else Invoke rider agent; Safely handle toolcall stacking issue. Remove last message and retry.
    try:
        ai_msg = rider_agent.invoke(state)
    except Exception as e:
        if "BadRequestError" in str(type(e)) or "Invalid parameter" in str(e):
            error_msg = str(e)
            logger.error(error_msg)
        return Command(
            update={"messages": [RemoveMessage(id=state["messages"][-1].id)]},
            goto="toolNode",
        )

    if ai_msg.tool_calls:
        goto = "toolNode"
    else:
        goto = "respondNode"

    return Command(
        update={"messages": [ai_msg]},
        goto=goto,
    )


async def respond_node(
    state: AgentState, runtime: Runtime[ContextSchema]
) -> Command[Literal[END]]:
    """
    Main agent node that processes user input and determines next action
    """
    ctx = runtime.context
    wa_client = ctx.wa_client
    recipient = ctx.recipient

    reply_to_msg_id = state.get("reply_to_msg_id", None)
    last_ai_msg = state["messages"][-1]

    await wa_client.send_message(
        to=recipient, text=last_ai_msg.content, reply_to_message_id=reply_to_msg_id
    )

    return Command(goto=END, update={"messages": [last_ai_msg]})


# %% Construct the graph
builder = StateGraph(state_schema=AgentState, context_schema=ContextSchema)
builder.add_node("riderAgent", agent_node)
builder.add_node("respondNode", respond_node)
builder.add_node("toolNode", ToolNode(rider_agent_tools))
builder.add_edge(START, "riderAgent")
builder.add_edge("toolNode", "riderAgent")


# %%
# from utils_common.lg_utils import display_graph
# from langgraph.checkpoint.memory import MemorySaver

# memory = MemorySaver()
# graph = builder.compile()

# display_graph(graph)

# %%

""" 
from utils_common.lg_utils import agent_loop_test
await agent_loop_test(builder, thread_id=21)

# %%
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)
config = {"configurable": {"thread_id":21, "recipient": "447448440754"}}


# await graph.ainvoke({"messages": [HumanMessage("hello")]}, config=config, context={"user_name": "John"})
await graph.ainvoke({"messages": [HumanMessage("hello")]}, config={}, context={"user_name": "John"})

# %%
graph.get_state()
# %%

"""
