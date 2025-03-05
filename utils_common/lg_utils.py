#%%
from typing import Any, List
from IPython.display import Image, display
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolInvocation
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    ToolMessage,
    RemoveMessage,
    filter_messages
)
from langgraph.graph import END, StateGraph, START

from langgraph.graph.state import CompiledStateGraph
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import BaseModel, Field
import json
from typing import List, Dict, Any
from utils_common.thread_management import ThreadHandler
from langchain_core.runnables.config import RunnableConfig
    
#%%
def create_agent(llm, tools, system_message: str):
    """Create an agent."""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful AI assistant, collaborating with other assistants."
                " Use the provided tools to progress towards answering the question."
                " If you are unable to fully answer, that's OK, another assistant with different tools "
                " will help where you left off. Execute what you can to make progress."
                " If you or any of the other assistants have the final answer or deliverable,"
                " prefix your response with FINAL ANSWER so the team knows to stop."
                " You have access to the following tools: {tool_names}.\n{system_message}",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )
    prompt = prompt.partial(system_message=system_message)
    prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
    return prompt | llm.bind_tools(tools)

#%%
def agent_node(state, agent, name):
    """
    Processes the given state with the specified agent and returns a formatted message.

    Args:
        state: The current state to be processed by the agent.
        agent: An object that has an `invoke` method to process the state.
        name: The name to be used in the message header.

    Returns:
        A dictionary containing a list of messages, where each message includes
        the agent's output and the specified name.
    """
    result = agent.invoke(state)
    return {"messages": [HumanMessage(content=result["output"], name=name)]}


#%%
LLM_4o = ChatOpenAI(
    model="gpt-4o-mini-2024-07-18", 
    temperature=0, 
    max_tokens=None, 
    timeout=None, 
    max_retries=2
)

# %%

client = OpenAI()

def generate_embedding(text):
    response = client.embeddings.create(
        input=text,
        model='text-embedding-3-small'
    )
    return response.data[0].embedding

# LLM_4o.invoke("tell me a joke; return json", response_format={"type": "json_object"})
#%%
def create_agent_w_sys_prompt(system_prompt, llm=LLM_4o):
    """
    Create an agent chain with the given system prompt and language model.

    Args:
        system_prompt (str): The system prompt for the agent chain.
        llm (langchain.llms.base.BaseLLM, optional): The language model to use for the agent chain.
            Defaults to LLM_4o.

    Returns:
        langchain.agents.agent.AgentExecutor: The created agent chain.

    Usage:
        agent_chain = create_agent_chain(system_prompt)
        response = agent_chain.invoke({"messages": [
            HumanMessage("hi, what can you help me with?")
        ]})
        print(response.content)
    """
    agent_chain_prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("placeholder", "{messages}")]
    )

    agent_chain = agent_chain_prompt | llm
    return agent_chain


def create_agent_w_tools_so_prompt(system_prompt, response_model=None | BaseModel, tools=[], llm=LLM_4o):
    """
    Create an agent chain, bind_tools -> response_model -> sys_prompt

    Args:
        system_prompt (str): The system prompt for the agent chain.
        llm (langchain.llms.base.BaseLLM, optional): The language model to use for the agent chain.
            Defaults to LLM_4o.

    Returns:
        langchain.agents.agent.AgentExecutor: The created agent chain.

    Usage:
        agent_chain = create_agent_chain(system_prompt)
        response = agent_chain.invoke({"messages": [
            HumanMessage("hi, what can you help me with?")
        ]})
        print(response.content)
    """
    agent_chain_prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("placeholder", "{messages}")]
    )
    
    if len(tools) == 0:
        agent_chain = agent_chain_prompt | llm    
        return agent_chain

    if response_model is None:
        llm_w_tools = llm.bind_tools(tools)
    else:
        llm_w_tools = llm.bind_tools(tools).with_structured_output(response_model)

    agent_chain = agent_chain_prompt | llm_w_tools    
    return agent_chain


def create_agent_w_sys_prompt_n_tools(
    system_prompt, 
    tools=[], 
    llm=LLM_4o, 
    parallel_tool_calls=True
    ):
    """
    Create an agent chain, bind_tools -> response_model -> sys_prompt

    Args:
        system_prompt (str): The system prompt for the agent chain.
        llm (langchain.llms.base.BaseLLM, optional): The language model to use for the agent chain.
            Defaults to LLM_4o.

    Returns:
        langchain.agents.agent.AgentExecutor: The created agent chain.

    Usage:
        agent_chain = create_agent_chain(system_prompt)
        response = agent_chain.invoke({"messages": [
            HumanMessage("hi, what can you help me with?")
        ]})
        print(response.content)
    """
    agent_chain_prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("placeholder", "{messages}")]
    )
    
    if len(tools) == 0:
        agent_chain = agent_chain_prompt | llm    
        return agent_chain
    if not parallel_tool_calls:
        llm_w_tools = llm.bind_tools(tools, parallel_tool_calls=False)
    else:
        llm_w_tools = llm.bind_tools(tools)

    agent_chain = agent_chain_prompt | llm_w_tools    
    return agent_chain

# %% Extract and parse state variables from tool_msgs
def extract_state_fields_from_tool_msgs(state):
    messages = state["messages"]
    last_message = messages[-1]

    if not isinstance(last_message, BaseMessage):
        return {}

    if 'Error' in last_message.content:
        # check for error in the tool msg
        return {
            **state
        }
    tool_msgs = filter_messages(state["messages"], include_types=['tool'])
    result_dict = {}
    for tool_msg in tool_msgs:
        if 'Error' not in tool_msg.content:
            try:
                data = json.loads(tool_msg.content)
                result_dict.update(data)
            except json.JSONDecodeError:
                # If parsing fails, skip to the next message
                continue
    ## Only extract state_vals if present
    return result_dict.get('state_fields',{})


def display_graph(compiled_graph: Any) -> None:
    try:
        display(Image(compiled_graph.get_graph(xray=True).draw_mermaid_png()))
    except Exception:
        # This requires some extra dependencies and is optional
        pass


def call_agent_chain(state, chain, config):
    """
    Calls the agent chain and returns the response.

    Args:
        state (dict): The current state of the conversation.
        chain (LLMChain): The agent chain to be invoked.
        config (dict): The configuration for the agent chain.

    Returns:
        dict: A dictionary containing the agent's response.

    Usage:
        workflow.add_node("agent", partial(call_agent_chain, chain=agent_chain))
    """
    # thread_id = config["configurable"].get("thread_id")
    # messages = state["messages"]
    response = chain.invoke(state)
    return {
        **state, 
        "messages": [response]
        }


# Define the function to execute tools (This is not needed anymore - ToolNode)
def call_tool(state, config, tool_executor):
    messages = state["messages"]
    last_message = messages[-1]

    # We construct an ToolInvocation from the function_call
    tool_call = last_message.tool_calls[0]
    action = ToolInvocation(
        tool=tool_call["name"],
        tool_input=tool_call["args"],
    )
    
    response = tool_executor.invoke(action)

    # We use the response to create a ToolMessage
    tool_message = ToolMessage(
        content=str(response), name=action.tool, tool_call_id=tool_call["id"]
    )
    
    # We return a list, because this will get added to the existing list
    return {"messages": [tool_message]}

# %% dispaly graph
def display_graph(compiled_graph: Any) -> None:
    try:
        display(Image(compiled_graph.get_graph(xray=True).draw_mermaid_png()))
    except Exception:
        # This requires some extra dependencies and is optional
        pass



#%%
class FormattedResponse(BaseModel):
    """Response formatter. ONLY formats what is available in the input. Does not offer additional options"""

    general_ai_response: str = Field(description="General response from ai, could be a question, greeting and a probe to select from options")
    options: List[str] = Field(default=None, description="If input is a question, this will a list Options to be presented to the user so user can select, can be None if there are no options or if its not a question.")


prompt = ChatPromptTemplate.from_messages([
    ("system", """
        You are an expert and accurate text formatter. You will be provided with
        an AI Response as input
        Your task is to extract the `general_ai_response` and the options presented.
        You can reframe general_ai_response is such as to select the prompt selecting the option
        There can be cases where there will be no options at all, you just return general_ai_response.
        Follow these instruction at all time:
        1. You will **NOT Hallucinate**
        2. Only provide options to the user if they are present in the input. 
        3. You have to work with ONLY what you have been provided with
        4. Shorten options values, length cannot exceed 20
        examples = [
        {{
            input:  If you have any questions or need to place an order, please let me know.
            output: {{'general_ai_response': 'let me know how I can help', 'options': ['Query', 'Place Order']}}
            }},
        {{
            input:  you can dine in or takeaway
            output: {{'general_ai_response': 'What were you looking to do', 'options': ['Dine-in', 'Take Away']}}
            }},
        {{
            input:  I am awaiting for the payment
            output: {{'general_ai_response': 'I am awaiting for the payment', 'options': []}}
            }},
        ]
    """),
    ("user", "{input}")
])

response_formatter_agent = prompt | LLM_4o.with_structured_output(FormattedResponse, method="json_schema")

# example_text = "Hello! Welcome to Trishna. How can I assist you today? You can ask about our restaurant, menu, or if you're interested in placing an order for takeaway or dine-in."
# formatted_response: FormattedResponse = response_formatter_agent.invoke(example_text)
# formatted_response, formatted_response.options[:3]


# %%

def is_last_tool_call(graph: CompiledStateGraph, config, tool_call_nm='send_acknowledgement_email'):
    """
    Check if the most recent tool call in the specified graph's state matches the given tool call name.

    This function retrieves the messages from the state of the CompiledStateGraph for the provided configuration.
    It then filters these messages to find the last message of type 'tool'. If the last tool message is found,
    it compares its name to the specified tool call name.

    Args:
        graph (CompiledStateGraph): The compiled state graph containing the state and messages to be evaluated.
        config (dict): The configuration object used to retrieve the relevant state from the graph.
        tool_call_nm (str): The name of the tool call to check against the last tool message. Defaults to
                            'send_acknowledgement_email'.

    Returns:
        bool: True if the last tool message's name matches the specified tool call name, False otherwise.
               Returns False if there are no messages present.
    
    Usage:
        is_last_tool_call(err_lead_capture_graph, config)
    """
    msgs = graph.get_state(config).values.get('messages')
    
    if msgs is None:
        return False

    # Print the msgs
    print(config)
    [msg.pretty_print() for msg in msgs]
    filtered_msgs = filter_messages(msgs, include_types=['tool'])
    last_tool_msg: ToolMessage = filtered_msgs[-1] if filtered_msgs else None

    if last_tool_msg is not None and last_tool_msg.name == tool_call_nm:
        return True
    else:
        return False

# %%

def is_json(s: str) -> bool:
    """Check if a string is a valid json or not"""
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False

# %% get recent messages
def get_recent_messages(messages: List, num_msgs=7):
    """
    Retrieve recent messages, with special handling for the last ToolMessage.

    Args:
        messages (List): Message list to retrieve from.
        num_msgs (int, optional): Number of recent messages. Defaults to 7.

    Returns:
        List: Recent messages, potentially including an extra message if last is a ToolMessage.
    """
    # Ensure num_msgs does not exceed the total number of messages
    num_msgs = min(num_msgs, len(messages))
    
    # check if the last message is a tool message
    if num_msgs > 0 and isinstance(messages[-num_msgs], ToolMessage):
        return messages[-(num_msgs+1):] if num_msgs < len(messages) else messages
    else:
        return messages[-num_msgs:]

# %% Print state values
def get_state_values(state, exclude_key='messages'):
    state_dict = {}
    for key, value in state.items():
        if key != exclude_key:
            state_dict[key] = value

            print(f"{key}: {value}") # Keep the print for now
    return state_dict

# %% Get Config for recipient

async def get_config_for_recipient(recipient: str, pool) -> Dict[str, Any]:
    """
    Retrieves or creates a thread for a recipient and returns a configuration dictionary.
    Also create passes a connection pool that can be used by tools !!!

    Args:
        recipient: The recipient identifier (e.g., a user ID).
        pool: The connection pool used by the ThreadHandler.

    Returns:
        A dictionary containing configuration information, including the thread ID and recipient.
    """
    thread_handler = ThreadHandler(pool)
    thread_id, _ = await thread_handler.get_or_create_thread(
        recipient
    )

    config = {"configurable": {"thread_id": thread_id, "recipient": recipient, 'pool':pool}}
    return config

#%%

def get_thread_from_config(config: RunnableConfig) -> str:
    """Extracts the thread_id from the config."""
    return config['configurable']['thread_id']


def get_recipient_from_config(config: RunnableConfig) -> str:
    """Extracts the recipient from the config."""
    return config['configurable']['recipient']
    
# %% Shorten the msgs

def shorten_state_messages(messages: List[dict]) -> List[Dict[str, Dict[str, Any]]]:
    """
    Shortens a list of message objects by extracting specific fields.

    Args:
        messages: A list of message objects, each expected to have a 'model_dump' method.

    Returns:
        A list of dictionaries, where each dictionary represents a shortened message
        in the format {type(message).__name__: message_dict}, 
        and message_dict contains only the fields in MSG_COLS.
    """
    MSG_COLS = ['content', 'additional_kwargs']
    
    short_msgs: List[Dict[str, Dict[str, Any]]] = [
        {type(_msg).__name__: _msg.model_dump(include=MSG_COLS)}
        for _msg in messages
    ]
    short_msgs.reverse()
    return short_msgs
# is_last_tool_call(err_lead_capture_graph, 'send_acknowledgement_email')

# %% Delete messages
def delete_messages(state):
    messages = state["messages"]
    if len(messages) > 3:
        return {"messages": [RemoveMessage(id=m.id) for m in messages[:-3]]}

# %% Display graph using mermaid 
# takeaway_graph.get_graph(xray=True).draw_mermaid()

# %% Building test graph based on agent, tools- it provides a toolNode to execute tools
# from langchain_core.runnables.base import RunnableSequence
# from langchain_core.tools.structured import StructuredTool
# from typing import List


# def create_test_graph(agent: RunnableSequence, agent_state, tools: List[StructuredTool]):
#   # Define node
#   def agent_node(agent_state) -> Command[Literal["toolNode", END]]:
#         ai_msg = takeaway_agent.invoke(state)

#         if ai_msg.tool_calls:
#             goto = "toolNode"
#         else:
#             goto = END

#         state_fields_from_tool_calls: dict = extract_state_fields_from_tool_msgs(state)

#         return Command(
#             update={"messages": [ai_msg], **state_fields_from_tool_calls},
#             goto=goto,
#         )

#   # Build graph
#   builder = StateGraph(agent_state)
#   builder.add_node("agentNode", takeaway_agent_node)
#   builder.add_node("toolNode", ToolNode(takeaway_tools))
#   builder.add_edge(START, "agentNode")
#   builder.add_edge("toolNode", "agentNode")

#   display_graph(takeaway_graph_test)

#   return builder