# %%
"""
Conversation state definitions for Elai Ordelo agents.
    . Provides TypedDict `AgentState` schema used by LangGraph graphs
    . Holds message history and delivery job context like dispatch_id and tracking url
"""
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from typing import Annotated, Sequence
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    wa_user_name: str
    dispatch_id: int
    order_number: str
    start_live_tracking_url: str
    delivery_start_dtts: str
    
    
