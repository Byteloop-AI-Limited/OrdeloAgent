"""
Order database operations and models (new version)
  . Defines OrderItem Pydantic model for individual order items
  . Generates unique order references with hashing and encoding
  . Creates order items from WhatsApp Order/Product objects
  . Order writes use the atomic RPC in order_service; no independent insert path
  . Calculates order totals from WhatsApp orders
  Functions/Classes:
    . OrderItem
    . get_order_total
    . create_order_reference
    . create_order_items_from_order
"""

# %%
# Standard library imports
import hashlib
from datetime import datetime
from typing import List, Optional

# Third-party imports
from dataclasses import asdict
from pydantic import BaseModel
from pywa.types import Order, Product

# Local imports
from config import project_settings

# %%
SALT = project_settings.salt
ALPHABET = "abcdefghijklmnopqrstuvwxyz"


class OrderItem(BaseModel):
    order_id: str
    sku: str
    quantity: int
    price: float
    product_name: str
    modifications: Optional[List[str]] = None


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


# Orders are created through order_service.create_order_with_items and its atomic RPC.
