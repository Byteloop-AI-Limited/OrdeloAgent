# %%
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
    
