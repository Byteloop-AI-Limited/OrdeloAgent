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

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from utils_common.order_management.order_db_ops import (
    OrderHandler,
    create_order_summary_from_db,
    get_stripe_payment_link,
    process_order_into_db,
)
from utils_common.thread_management import ThreadHandler

from utils_common.lg_utils import (
    shorten_state_messages,
    get_state_values,
    get_config_for_recipient,
)
from utils_common.inventory_management.product_update import update_availability
from utils_common.db_utils.sbase_rest_ops import update_sbase_data, select_sbase_data


# %% Funcs


# %%
async def handle_reservation_confirmation(
    reservation_id: str,
    graph, 
    pool
    ):
    """
    Confirms a reservation and updates the system state accordingly.

    This function checks the confirmation status of a reservation and, if not already confirmed,
    updates the reservation status to 'confirmed' in the database. It then updates the state graph 
    to reflect the confirmation and sends a notification message to inform the user.

    Args:
        reservation_id: The unique identifier of the reservation.
        graph: The graph object to update the system state.
        pool: The database connection pool.

    Returns:
        A boolean indicating whether the reservation was already confirmed.
    """
    
    _rows = await select_sbase_data("reservation", reservation_id=reservation_id)
    
    is_already_confirmed = _rows[0]['confirmation_status'] == 'confirmed'
    recipient = _rows[0]['recipient']
    
    if not is_already_confirmed:
        _was_update_success = await update_sbase_data(
            table_name="reservation", 
            update_fields={'confirmation_status':'confirmed'},
            reservation_id=reservation_id
            )
        
        config = await get_config_for_recipient(recipient, pool)
        await graph.aupdate_state(
            config,
            {"is_reservation_confirmed": True},
            as_node="queryAgent",
        )

        # notify user
        ip_msgs = {
            "messages": [
                SystemMessage(f"Inform user that reservation {reservation_id} is confirmed"),
                # AIMessage(f"Reservation confirmed for {reservation_id}"),
            ]
        }
        await graph.ainvoke(input=ip_msgs, config=config)

    return is_already_confirmed

    


# %% runElaiGraph with human msg
async def run_elai_graph_with_human_msg(
    human_msg: str, 
    recipient: str, 
    graph, 
    pool
    ):
    """Executes the takeaway graph and returns the AI's response."""

    config = await get_config_for_recipient(recipient, pool)

    ip_msgs = {
        "messages": [
            HumanMessage(human_msg),
        ]
    }

    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)
    ai_msg_content = ai_msg["messages"][-1].content

    return ai_msg_content

# %% runElaiGraph
async def run_elai_graph(msg: Message, graph, pool):
    """Executes the takeaway graph and returns the AI's response."""
    human_msg = msg.text
    recipient = msg.sender
    wa_user_name = msg.from_user.name

    config = await get_config_for_recipient(recipient, pool)

    # Check is name is captured
    state = await graph.aget_state(config=config)
    if not state.values.get("wa_user_name"):
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


# %% Handle Order
async def handle_order_and_graph_update(msg: Message, graph, pool) -> (str, str):
    recipient = msg.sender
    logger.info(msg.order)
    config = await get_config_for_recipient(recipient, pool)
    thread_handler = ThreadHandler(pool)

    (
        thread_id,
        is_new_thread_created,
    ) = await thread_handler.get_or_create_thread(recipient)

    # Process Order
    order_id = await process_order_into_db(
        pool, recipient=recipient, thread_id=thread_id, wa_order=msg.order
    )

    order_summary: str = await create_order_summary_from_db(pool, order_id=order_id)
    stripe_link: str = await get_stripe_payment_link(pool, order_id=order_id)

    # update graph
    _sys_msg = f"""
    Order from user: {json.dumps(order_summary)}. 
    Paymentlink is shared with user.
    Request user to complete the payment
    """

    config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}

    await graph.aupdate_state(
        config,
        {
            "order_summary": order_summary,
            "payment_link": stripe_link,
            "is_payment_successful": None,
            "messages": [SystemMessage(_sys_msg)],
        },
        as_node="toolNode",
    )

    return stripe_link, order_id


# %% Handle WA overrides
async def handle_payment_override_and_graph_update(msg: Message, graph, pool):
    """
    Handles the update of the payment status in the graph.

    Args:
        recipient: The recipient of the message
        graph: the graph object
        pool: the database connection pool
    """
    recipient = msg.sender
    thread_handler = ThreadHandler(pool)

    thread_id, _ = await thread_handler.get_or_create_thread(recipient)
    config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}

    # update graph
    await graph.aupdate_state(
        config,
        {
            "is_payment_successful": True,
        },
        as_node="toolNode",
    )

    ip_msgs = {
        "messages": [
            HumanMessage("I have completed the payment for takeaway"),
        ]
    }

    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)

    ai_msg_content = ai_msg["messages"][-1].content

    return ai_msg_content




# %% handle PaymentWebhook

async def handle_payment_webhook_and_graph_update(request_body, graph, pool):
    """
    Handles the update of the payment status in the graph.

    Args:
        recipient: The recipient of the message
        graph: the graph object
        pool: the database connection pool
    """
    order_id = request_body["data"]["object"]["metadata"]["orderID"]
    recipient = request_body["data"]["object"]["metadata"]["recipient"]
    thread_id = request_body["data"]["object"]["metadata"]["threadID"]

    order_handler = OrderHandler(pool)

    # Mark payment succesful on the order db
    if await order_handler.update_order(order_id=order_id):
        # Update graph state
        config = {"configurable": {"thread_id": thread_id, "recipient": recipient}}
        await graph.aupdate_state(
            config, {"is_payment_successful": True}, as_node="takeawayAgent"
        )
    else:
        return {"fail": "failed to update order"}

    # Run graph to notify the user
    ip_msgs = {
        "messages": [
            HumanMessage("I have completed the payment for takeaway"),
        ]
    }
    ai_msg = await graph.ainvoke(input=ip_msgs, config=config)
    ai_msg_content = ai_msg["messages"][-1].content
    
    return {"success": ai_msg_content}


# %% handle ReservationConfirmation
async def handle_reservation_confirmation_and_graph_update(msg: Message, graph, pool):
    """
    Handles the update of the payment status in the graph.

    Args:
        recipient: The recipient of the message
        graph: the graph object
        pool: the database connection pool
    """
    recipient = msg.sender
    config = await get_config_for_recipient(recipient, pool)

    # update graph
    await graph.aupdate_state(
        config,
        {
            "is_reservation_confirmed": True,
            "messages": [SystemMessage("Reservation Confirmed"), AIMessage("Reservation Confirmed")],
        },
        as_node="toolNode",
    )

    # Notify the user
    await msg.reply("Reservation Confirmed")



# %%
def admin_update_availability(msg: Message):
    skus_to_be_updated = []
    for product in msg.order.products:
        skus_to_be_updated.append(product.sku)

    update_availability(skus_to_be_updated, availability="out of stock")

    return True


# %% Debug State
async def debug_state(recipient: str, graph, pool) -> dict:
    config = await get_config_for_recipient(recipient, pool)
    state = await graph.aget_state(config=config)

    debug_stack = {
        **get_state_values(state.values),
        "messages": shorten_state_messages(state.values["messages"]),
    }
    return debug_stack


# %% debug food search
from langchain_core.runnables.config import RunnableConfig
from typing_extensions import Annotated
from typing import List
from enum import Enum
from utils_common.db_utils.sbase_rest_ops import get_sql_condition_new
from elai.agents.food_query    import _sql_search_for_condition, _vector_search_for_food_item
from pywa.types import ProductsSection


async def food_item_query_or_search_debug(
    food_item_query: str,
    food_type: str = None,
    price_val: str = None,
    is_crustacean: bool = None,
    contains_dairy: bool = None,
    contains_eggs: bool = None,
    contains_fish: bool = None,
    gluten_present: bool = None,
    nuts_present: bool = None,
    is_vegetarian: bool = None,
    is_vegan: bool = None
) -> dict:
    """
    A tool to help with a food item query or search.

    Args:
        food_item_query (str): The complete user query or user message, do not change the original text.
        food_type (str, optional): Type of the food item searched: ['Starter', 'Rice / Naan', 'Thali', 'Desserts', 'Side Order', 'Main', 'Biryani', 'Favourites', 'Drinks']
        price_val (str, optional): Price filter. Starts with comparison operators ('>', '<', '>=', '<=', '=') followed by a number, indicating user's intention. Eg: price greater than 10: '>10' 
        is_crustacean (bool, optional): contains crustaceans.
        contains_dairy (bool, optional): contains dairy.
        contains_eggs (bool, optional): contains eggs.
        contains_fish (bool, optional): contains fish.
        gluten_present (bool, optional): contains gluten.
        nuts_present (bool, optional): contains with nuts.
        is_vegetarian (bool, optional): is vegetarian.
        is_vegan (bool, optional): is vegan.

    Returns:
        dict: Communication to user about the products matching or similar to query
    """
    
    args = {
        "food_item_query": food_item_query,
        "food_type": food_type,
        "price_val": price_val,
        "is_crustacean": is_crustacean,
        "contains_dairy": contains_dairy,
        "contains_eggs": contains_eggs,
        "contains_fish": contains_fish,
        "gluten_present": gluten_present,
        "nuts_present": nuts_present,
        "is_vegetarian": is_vegetarian,
        "is_vegan": is_vegan
    }
    # Remove keys with None values
    args = {key: value for key, value in args.items() if value is not None}
    
    # Generate sql condition without food_item_query
    args.pop("food_item_query")
    sql_condition = get_sql_condition_new(**args)

    # sql search for conditions
    sql_search_results: List[dict] = _sql_search_for_condition(sql_condition)
    
    
    # vec search for food item 
    vec_search_ids: List[str] = _vector_search_for_food_item(food_item_query)
    logger.info(vec_search_ids)

    if not vec_search_ids:
        # If vec_search_ids is empty, return all results as-is
        logger.error("vec_search is empty")
        filtered_results = sql_search_results
    else:
        # Create a lookup for quick access
        result_map = {item['id']: item for item in sql_search_results}
        
        # Iterate over vec_search_ids to preserve order
        filtered_results = [result_map[v_id] for v_id in vec_search_ids if v_id in result_map]

    # Group results based on food_type
    grouped = {}
    for item in filtered_results:
        ftype = item['food_type']
        if ftype not in grouped:
            grouped[ftype] = []
        grouped[ftype].append(item['id'])

    product_sections: List[ProductsSection]=[
        ProductsSection(title=title, skus=sku)
        for title, sku in grouped.items()
    ]

    return product_sections