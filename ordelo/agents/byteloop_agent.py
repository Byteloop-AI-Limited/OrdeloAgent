# %%
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver
from utils_common.lg_utils import LLM_4o as llm
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt.chat_agent_executor import AgentState

# %%

checkpointer = InMemorySaver()


def prompt(state: AgentState, config: RunnableConfig) -> list[AnyMessage]:
    user_name = config["configurable"].get("user_name")
    system_msg = f"""
You are a helpful whatsapp based chat agent that holds natural conversation on behalf on a business `Byteloop Ai`.
user's name: {user_name}. 
Only use their name in important messages, like the first hello or when the user is being difficult. 
Their user name is picked up from user's whatsapp profile.

You can help users with any questions they have about the business. Here is the informattion about the business:
`Byteloop Ai is an AI technology provider focussed on building automation solutions for small to medium businesses.
We provide solutions for automating customer interactions. In order to disscuss further, user should send an email to admin@byteloop.ai`

Follow below instructions:
1. Politely decline any questions/tasks that are not related to the business.
2. Always maintain a professional and courteous tone.
3. If you are not sure about something, or if user wants to talk to someone, request them to send an email to admin@byteloop.ai. 
4. Reply with a max of 2 sentences. Dont be too verbose.
"""
    return [{"role": "system", "content": system_msg}] + state["messages"]


agent = create_react_agent(
    model=llm,
    tools=[],
    # A static prompt that never changes
    prompt=prompt,
    checkpointer=checkpointer,
)


# %%
# Run the agent

# config = {"configurable": {"thread_id": "1", "user_name": "John"}}

# %%
# ip_msgs = [{"role": "user", "content": "how did you get my name?"}]

# agent.invoke({"messages": ip_msgs}, config)
