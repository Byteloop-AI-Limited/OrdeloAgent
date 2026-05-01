"""
Order receipt generation and formatting utilities
  . Depends on FoodOrder, OrderItem, Supabase client, and typing helpers
  . Fetches order items from database for receipt generation
  . Formats order details and item-level modifications with WhatsApp-safe nested markers
  . Calculates order totals and item summaries
  . Generates customer-facing and restaurant-facing receipt text
  Functions/Classes:
    . _fetch_order_items
    . _format_order_item_lines
    . build_wa_order_reciept_for_cust
    . build_wa_order_reciept_for_rest
"""

# %%
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.order_db_ops_new import OrderItem
from config import client_ordelo
from typing import List, Tuple


def _fetch_order_items(order_id: str) -> List[dict]:
    """Helper to retrieve order_items rows for the given order_id.

    Args:
        order_id: Unique identifier of the order.

    Returns:
        A list of order_items rows as dictionaries. Falls back to an empty list
        if the query fails or no items are found.
    """
    try:
        response = (
            client_ordelo.table("order_item")
            .select("product_name, quantity, price, modifications")
            .eq("order_id", order_id)
            .execute()
        )
        return response.data or []
    except Exception as e:  # pragma: no cover – database/network failure
        print(f"⚠️  Failed to fetch order_items for {order_id}: {e}")
        return []


def _format_order_item_lines(items_data: List[dict]) -> List[str]:
    item_lines: List[str] = []
    for item in items_data:
        qty = item.get("quantity", 1)
        name = item.get("product_name", "Item")
        unit_price = item.get("price", 0)
        line_total = unit_price * qty
        item_lines.append(f"*• {qty} × {name}  –  £{line_total:.2f}*")

        modifications = item.get("modifications") or []
        if isinstance(modifications, str):
            modification_values = [modifications]
        else:
            try:
                modification_values = list(modifications)
            except TypeError:
                modification_values = [modifications]

        for modification in modification_values:
            modification_text = str(modification).strip()
            if modification_text:
                item_lines.append(f"   ↳ _{modification_text}_")

    return item_lines


# %%
# --------------------------------------------------------------------------------------
# Customer-facing receipt
# --------------------------------------------------------------------------------------


def build_wa_order_reciept_for_cust(
    order_id: str = None, food_order: FoodOrder = None
) -> Tuple[str, str]:
    """Create WhatsApp order-receipt text with basic markdown.

    The function fetches the *food_order* and *order_items* rows for the provided
    ``order_id`` and converts them into a WhatsApp-friendly receipt message.

    WhatsApp supports a subset of Markdown: ``*bold*``, ``_italic_`` and `````monospace````.
    We use ``*`` for bold highlights and a simple middle-dot (•) as a bullet.

    Args:
        order_id: The unique order ID (e.g. ``QPRX-28``).

    Returns:
        A tuple ``(header, text)`` suitable for the ``header`` and ``text``
        parameters in ``_async_wa_client.send_message``.
    """

    # 1️⃣ Fetch models
    if not food_order:
        order = FoodOrder.from_order_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
    else:
        order = food_order

    order_items = _fetch_order_items(order.order_id)
    if not order_items:
        raise ValueError(f"No order_items found for {order.order_id}")

    # 2️⃣ Build header
    header = f"Order #{order.order_number}"  # eg: Order #ELB-QPRX-28

    # 3️⃣ Build items list
    item_lines = _format_order_item_lines(order_items)

    items_block = "\n".join(item_lines)

    # 4️⃣ Build charges & totals
    charges_lines: List[str] = []
    if order.service_charge:
        charges_lines.append(f"Service charge: £{order.service_charge:.2f}")
    if order.delivery_fee:
        charges_lines.append(f"Delivery fee: £{order.delivery_fee:.2f}")
    if order.small_order_fee:
        charges_lines.append(f"Small order fee: £{order.small_order_fee:.2f}")

    charges_block = "\n".join(charges_lines)

    total_line = f"*Total:* £{order.final_order_value or order.total_price:.2f}"

    # 5️⃣ Assemble message text
    text_parts = [
        "*Items:*",  # title
        items_block,
    ]
    if charges_block:
        text_parts.extend(["", charges_block])
    text_parts.extend(["", total_line])

    text = "\n".join(text_parts).strip()

    return header, text


# --------------------------------------------------------------------------------------
# Restaurant-facing receipt (no service or delivery charge, total = total_price)
# --------------------------------------------------------------------------------------


def build_wa_order_reciept_for_rest(
    order_id: str = None,
    food_order: FoodOrder = None,
    order_items: List[OrderItem] = None,
) -> Tuple[str, str]:
    """Build WhatsApp receipt text for the restaurant.

    Differences vs. *build_wa_order_reciept_for_cust*:
        • Omits *Service charge* and *Delivery fee* lines.
        • ``Total`` reflects the *total_price* (food value) rather than the final
          customer-facing value.

    Args:
        order_id: Order ID to fetch order details (used if food_order not provided).
        food_order: FoodOrder Pydantic model (should be provided with order_items).
        order_items: List of OrderItem Pydantic models (should be provided with food_order).
    """
    if not food_order:
        order = FoodOrder.from_order_id(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
    else:
        order = food_order

    # Use provided order_items if available, otherwise fetch from DB
    if order_items is None:
        items_data = _fetch_order_items(order.order_id)
        if not items_data:
            raise ValueError(f"No order_items found for {order.order_id}")
    else:
        # Convert OrderItem Pydantic models to dict format for processing
        items_data = [
            {
                "quantity": item.quantity,
                "product_name": item.product_name,
                "price": item.price,
                "modifications": item.modifications,
            }
            for item in order_items
        ]

    header = f"Order #{order.order_number} (Kitchen)"

    # Items
    item_lines = _format_order_item_lines(items_data)

    items_block = "\n".join(item_lines)

    # Charges – only include small_order_fee if present and non-zero
    charges_lines: List[str] = []
    if order.small_order_fee:
        charges_lines.append(f"Small order fee: £{order.small_order_fee:.2f}")

    charges_block = "\n".join(charges_lines)

    total_line = f"*Total:* £{order.total_price:.2f}"

    text_parts = ["*Items:*", items_block]
    if charges_block:
        text_parts.extend(["", charges_block])
    text_parts.extend(["", total_line])

    return header, "\n".join(text_parts).strip()


# %%
""" Test
order_items = (
    client.table("order_item").select("*").eq("order_id", "QPRX-28").execute().data
)
# %%
food_order = FoodOrder.from_order_id("QPRX-28")

# %%

food_order, order_items

# %% sending whatsapp receipt
# Send as interactive message with URL button
from config import _async_wa_client as wa
from pywa.types import ButtonUrl

recipient = "447448440754"
href = "https://wa.me/447448440754"

address_confirmation_y = "y"
address_confirmation_n = "n"

header, text = build_wa_order_reciept_for_cust("TMCH-30")
header_rest, text_rest = build_wa_order_reciept_for_rest("TMCH-30")

await wa.send_message(
    to=recipient,
    header=header,
    text=text,
    reply_to_message_id=None,
    buttons=[
        Button(title="Notify Driver", callback_data=address_confirmation_y),
        Button(title="Confirmation Code", callback_data=address_confirmation_n),
    ],
)

await wa.send_message(
    to=recipient,
    header=header_rest,
    text=text_rest,
    reply_to_message_id=None,
    buttons=[
        Button(title="Notify Driver", callback_data=address_confirmation_y),
        Button(title="Confirmation Code", callback_data=address_confirmation_n),
    ],
)
"""
