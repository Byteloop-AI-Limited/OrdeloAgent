"""
Order database operations (new version with improved models)
  . Defines OrderItem and FoodOrder Pydantic models
  . Generates unique order IDs and order numbers
  . Inserts WhatsApp orders into database with validation
  . Handles order item creation from WhatsApp Product objects
  . Validates and enriches order data before database insertion
  Functions/Classes:
    . OrderItem
    . FoodOrder
    . generate_order_id
    . generate_order_number
    . insert_wa_order
"""

# %%
# Standard library imports
import hashlib
from datetime import datetime
from typing import Dict, List

# Third-party imports
from dataclasses import asdict
from pydantic import BaseModel
from pywa.types import Order, Product

# Local imports
from config import client, project_settings, logger

# from config.params import REST_MASTER
from utils_common.params import filter_dict

# %%
SALT = project_settings.salt
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


class OrderItem(BaseModel):
    order_id: str
    sku: str
    quantity: int
    price: float
    product_name: str


# %%
wa_order = Order(
    catalog_id="875083621367251",
    products=(
        Product(sku="apple_and_mango_smoothie", quantity=2, price=5.95, currency="GBP"),
        Product(sku="aloo_gobi", quantity=3, price=9.95, currency="GBP"),
    ),
    text="",
)


# %%
def get_order_total(wa_order: Order) -> float:
    order_total: float = 0.0
    for product in wa_order.products:
        order_total += product.price * product.quantity
    return round(order_total, 2)


def create_order_reference(
    recipient: str, order_dt: str = datetime.now().strftime("%Y-%m-%d")
):
    """Creates a unique order number based on recipient and order date."""

    number = recipient[-4:]
    """Encodes a 4-digit number string into a 4-character string."""
    if not len(number) == 4 or not number.isdigit():
        raise ValueError("Number must be a 4-digit string")

    salted_number = f"{number}{SALT}{order_dt}"
    hashed_number = hashlib.sha256(salted_number.encode()).hexdigest()

    encoded_chars: str = ""
    for i in range(4):
        index = int(hashed_number[i * 2 : i * 2 + 2], 16) % len(ALPHABET)
        encoded_chars += ALPHABET[index]

    return encoded_chars.upper()


# %% Create order items
async def create_order_items_from_order(
    wa_order: Order, order_id: str
) -> List[OrderItem]:
    """
    Transforms Order to list of OrderItem objects with product names and order id.

    Args:
        wa_order: The Order object with products
        order_id: ID to associate with order items

    Returns:
        List of OrderItem objects
    """
    order_items: List[OrderItem] = []

    for product in wa_order.products:
        _dict = asdict(product)
        _dict["order_id"] = order_id
        _dict["sku"] = product.sku
        _order_item = OrderItem(**_dict)
        order_items.append(_order_item)
    return order_items


# %% Insert into FoodOrder
async def insert_order_items(order_id: str, wa_order: Order):
    order_items: List[OrderItem] = await create_order_items_from_order(
        wa_order, order_id
    )

    response = (
        client.table("order_item")
        .insert([x.model_dump() for x in order_items])
        .execute()
    )

    return response


async def insert_wa_order(recipient: str, thread_id: str, wa_order: Order):
    order_dt: str = datetime.now().strftime("%Y-%m-%d")
    # Build the insert payload
    # get next sequence number
    seq_number = client.rpc("get_next_daily_seq", {"input_date": order_dt}).execute()
    # create order reference for given recipient and date
    order_reference = create_order_reference(recipient, order_dt)
    order_id = f"{order_reference}-{seq_number.data}"
    # order_number = f"{REST_MASTER.rest_ref}-{order_reference}-{seq_number.data}"
    order_number = "Dummy"
    insert_payload = {
        "order_id": order_id,
        "order_number": order_number,
        "seq_id": seq_number.data,
        "recipient": recipient,
        "thread_id": thread_id,
        "action": "delivery",
        "total_price": wa_order.total_price,
        "payment_status": "requires_payment",
    }

    # Insert into FoodOrder
    try:
        food_order_response = (
            client.table("food_order").insert(insert_payload).execute()
        )
        if not food_order_response.data:
            # Handle case where insert might appear successful but returns no data
            logger.error(f"Warning: Inserting food order {order_id} returned no data.")
            # Not attempting rollback here as nothing was confirmed inserted
            return {
                "success": False,
                "error": "No data returned from food_order insert",
            }
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error inserting food order {order_id}: {error_message}")
        return {
            "success": False,
            "error": "Failed to insert food order",
            "details": error_message,
        }

    # Create and Insert order_items - only proceed if food_order insert was successful
    try:
        order_items: List[OrderItem] = await create_order_items_from_order(
            wa_order, order_id
        )
        order_items_response = (
            client.table("order_item")
            .insert([x.model_dump() for x in order_items])
            .execute()
        )
        if not order_items_response.data:
            # Handle case where insert might appear successful but returns no data
            logger.error(
                f"Warning: Inserting order items for order {order_id} returned no data."
            )
            # Attempt to delete the potentially orphaned food_order
            try:
                client.table("food_order").delete().eq("order_id", order_id).execute()
                logger.error(
                    f"Rollback attempted: Deleted food_order {order_id} due to order_item insert issue (no data)."
                )
            except Exception as del_e:
                logger.error(
                    f"Error during rollback: Failed to delete food_order {order_id}: {del_e}"
                )
            return {
                "success": False,
                "error": "No data returned from order_item insert operation",
                "details": "Insert seemed successful but no data was returned. Rollback attempted.",
            }
    except Exception as e:
        error_message = str(e)
        logger.error(
            f"Error inserting order items for order {order_id}: {error_message}"
        )
        # Attempt to delete the potentially orphaned food_order
        try:
            client.table("food_order").delete().eq("order_id", order_id).execute()
            logger.error(
                f"Rollback attempted: Deleted food_order {order_id} due to order_item insert failure."
            )
        except Exception as del_e:
            logger.error(
                f"Error during rollback: Failed to delete food_order {order_id}: {del_e}"
            )
        return {
            "success": False,
            "error": "Failed to insert order items",
            "details": error_message + ". Rollback attempted.",
        }

    # If both inserts succeeded and returned data
    return order_id, order_number


# %% reference table select


async def create_order_summary(order_id: str) -> Dict:
    response = (
        client.table("order_item")
        .select("""
            product_name, 
            quantity, 
            price, 
            food_order(
                order_id, 
                order_type, 
                payment_status, 
                recipient, 
                thread_id
                )
            )
        """)
        .eq("order_id", order_id)
        .execute()
    )

    food_order_data = response.data[0]["food_order"]
    order_items_data = filter_dict(
        response.data, select_cols=["product_name", "price", "quantity"]
    )

    order_summary_dict: dict = {
        **food_order_data,
        "items": order_items_data,
        "currency": "GBP",
    }
    return order_summary_dict


""" Test 
# %%
import requests 
def get_pricing_details(order_number, total_food_value, distance_in_miles):
    url = "https://vfw8b9byz3.execute-api.eu-west-2.amazonaws.com/prod/pricing"
    
    payload = {
        "order_number": order_number,
        "total_food_value": total_food_value,
        "distance_in_miles": distance_in_miles
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    else:
        return {"error": f"Failed to get pricing: {response.status_code}", "details": response.text}


get_pricing_details("test_8004", 10.99, 2)
"""
