# %%
"""LangGraph orchestration for Byteloop's WhatsApp concierge agent.

Configures the prompt, tools, and runtime context used to run a ReAct-style
agent that can chat with customers, trigger WhatsApp notifications, and access
shared resources such as the async Postgres pool and thread handler.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState
from psycopg_pool import AsyncConnectionPool
from pywa_async import WhatsApp
from utils_common.lg_utils import LLM_4o as llm
from utils_common.thread_management.thread_handler import ThreadHandler

# %%

checkpointer = InMemorySaver()


def prompt(state: AgentState, config: RunnableConfig) -> list[AnyMessage]:
    # user_name = config["configurable"].get("user_name")
    user_name = "10hith"
    system_msg = f"""
You are a helpful WhatsApp-based chat agent that holds natural conversations on behalf of the business `Byteloop Ai`.
user's name: {user_name}.
Only use their name in important messages, like the first hello or when the user is being difficult.
Their user name is picked up from the user's WhatsApp profile.

You can help users with any questions they have about the business. Here is the information about the business:
`Byteloop Ai is an AI technology provider focused on building automation solutions for small to medium businesses.
We provide solutions for automating customer interactions. In order to discuss further, the user should send an email to admin@byteloop.ai`

Follow the instructions below:
1. Politely decline any questions/tasks that are not related to the business.
2. Always maintain a professional and courteous tone.
3. If you are not sure about something, or if the user wants to talk to someone, request that they send an email to admin@byteloop.ai.
4. Reply with a maximum of 2 sentences. Don't be too verbose.
5. Use the `send_user_notification_on_whatsapp` tool whenever you need to send proactive notifications or confirmations to the user.
"""
    return [{"role": "system", "content": system_msg}] + state["messages"]


# %% Tools
from langgraph.prebuilt import ToolNode, InjectedState
from typing import Annotated
from langchain_core.tools.base import InjectedToolCallId
from utils_common.lg_utils import (
    create_agent_w_sys_prompt_n_tools,
    get_recipient_from_config,
)
from langgraph.runtime import get_runtime


async def send_user_notification_on_whatsapp(
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> dict:
    """
    This tool sends a notification to the user on whatsapp.

    Args:
        None

    Returns:
        dict: Agent to respond as instructed by the tool message.
    """
    recipient = get_recipient_from_config(config)
    ctx = get_runtime(ContextSchema).context
    wa = ctx.wa_client
    print(type(ctx.pool))
    await wa.send_message(recipient, "Hello")
    return "message send to user on whatsapp"


# %%


class ContextSchema(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    pool: AsyncConnectionPool
    wa_client: WhatsApp
    thread_handler: ThreadHandler | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.thread_handler is None:
            self.thread_handler = ThreadHandler(self.pool)


# %%

graph = create_react_agent(
    model=llm,
    tools=[send_user_notification_on_whatsapp],
    # A static prompt that never changes
    prompt=prompt,
    checkpointer=checkpointer,
    context_schema=ContextSchema,
)


# %%
# Run the agent
from config import pg_settings, _async_wa_client

config = {"configurable": {"thread_id": "4", "recipient": "447448440754"}}

# context = ContextSchema(
#     user_name="10hith", pool=await pg_settings.get_pool(), wa_client=_async_wa_client
# )
# # %%
# ip_msgs = [{"role": "user", "content": "send a notification to me on whatsapp"}]

# await graph.ainvoke({"messages": ip_msgs}, config=config, context=context)
