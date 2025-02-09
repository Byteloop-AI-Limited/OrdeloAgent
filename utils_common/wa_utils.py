#%%
from pywa import WhatsApp
from pywa.types import SectionList, Section, SectionRow, Button, CallbackButton
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.exceptions import OutputParserException


### Send formatted response
from utils_common.lg_utils import response_formatter_agent, FormattedResponse

def wa_send_formatted_response(graph_response: str, recipient, wa):
    formatted_response: FormattedResponse = response_formatter_agent.invoke(graph_response)
    buttons = [Button(title=option[:19], callback_data=option) for option in formatted_response.options[:3]]
    text = formatted_response.general_ai_response
    print(f"GraphResponseIs: {graph_response}")
    print(f"FormattedResponseIs: {text}")
    wa.send_message(
        to=recipient,
        text=text,
        # footer='⚡Ever-Ready AI',
        buttons=buttons,
    )
    return

#%%
def ai_response_to_json(ai_response: str) -> dict:
    _ai_response = lambda input: ai_response 
    parser_chain = _ai_response | JsonOutputParser()
    
    try:
        json_output = parser_chain.invoke(input='')
        return json_output
    except OutputParserException as e:
        # Handle the output parser exception, e.g., logging or returning an error message
        print(f"OutputParserException occurred: {e}")
        return {"Error":"OutputParserException occurred:"}
    

async def send_button_options(formatted_response: FormattedResponse, recipient, wa):
    buttons = [Button(title=option[:19], callback_data=option) for option in formatted_response.options[:3]]
    text = formatted_response.general_ai_response
    await wa.send_message(
        to=recipient,
        text=text,
        # footer='⚡ByteloopAi',
        buttons=buttons,
    )


def send_section_options(ai_msg_dict, recipient, wa):
    section_rows = [SectionRow(title=option[:19], callback_data=option) for option in ai_msg_dict['options']]
    text = ai_msg_dict['response']
    wa.send_message(
        to=recipient,
        text=text,
        footer='⚡ ByteloopAi',
        buttons=SectionList(
            button_title="options",
            sections=[Section(title="options", rows=section_rows)]
            ),
    )
    return

def run_graph_n_respond_w_ui(graph: CompiledStateGraph, human_msg_content: str, recipient: int, wa: WhatsApp):
    # Invoke the graph
    thread = {"configurable": {"thread_id": recipient}}
    new_state = graph.invoke({'messages': [
        HumanMessage(human_msg_content)
        ]}, config=thread
    )
    file_url = 'https://replicate.delivery/yhqm/KBUbZaUUajLjLdzzt4XTsfXqQuqomZk9ObWoLyO2vXpYTotJA/out-0.webp'
    wa.send_image(
        to=recipient,
        image=file_url
    )
    wa.send_message(
            to=recipient,
            text=f"hi there muthofucka; here is the link {file_url}",
            footer='⚡ ByteloopAi',
        )
    
    ai_msg = new_state['messages'][-1].content
    # Parse as Json
    ai_msg_dict = ai_response_to_json(ai_msg)
    print(f"ai_msg_dict is {ai_msg_dict}")
    
    # Send msg
    options = ai_msg_dict.get('options', [])
    if len(options) > 0 and len(options) <= 3:
        send_button_options(ai_msg_dict, recipient, wa)
    elif len(options) > 3:
        send_section_options(ai_msg_dict, recipient, wa)
    else:
        text = ai_msg_dict.get('response', 'No response available.')
        wa.send_message(
            to=recipient,
            text=text,
            footer='⚡ ByteloopAi',
        )

        