# %%
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage
from typing import Annotated, Sequence
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    wa_user_name: str
    next_agent: str
    order_id: str
    order_summary: dict
    is_reservation_confirmed: bool
    is_payment_successful: bool
    payment_link: str
    reservation_dt: str
    
