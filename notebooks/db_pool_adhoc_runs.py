# %%
from config import client_ordelo
import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List

# Generate random test values
order_id = f"ESUY-24"
order_number = f"SFCS-ESUY-24"
seq_number_data = 42  # Simulating seq_number.data
recipient = "447448440754"  # Test phone number
notes = "Extra spicy, no onions"
modifications = ["Extra cheese", "Well done", "No pickles"]
thread_id = f"thread_{uuid.uuid4().hex[:12]}"
action = "new_order"
total_price = 24.99
payment_status = "requires_payment"

# %%
from utils_common.order_management.food_order_pymodel import FoodOrder

order_id = "HXKS-29"
food_order = FoodOrder.from_order_id(order_id)
payment_uri = food_order.payment_uri
intent_payload = await food_order.gen_payment_intent_payload()
intent_payload
# %%
insert_payload = {
    "order_id": order_id,
    "order_number": order_number,
    "seq_id": seq_number_data,
    "recipient": recipient,
    "notes": notes,
    "modifications": modifications,
    "thread_id": thread_id,
    "action": action,
    "total_price": total_price,
    "payment_status": payment_status,
}

# Insert into food_order
try:
    food_order_response = (
        client_ordelo.table("food_order").insert(insert_payload).execute()
    )
    print(f"✓ Inserted order: {order_number}")
    print(f"Response: {food_order_response.data}")
except Exception as e:
    print(f"✗ Error inserting food_order: {e}")


# %%
class OrderItem(BaseModel):
    order_id: str
    sku: str
    quantity: int
    price: float
    product_name: str
    modifications: Optional[List[str]] = None


# Create sample order items
order_items = [
    OrderItem(
        order_id=order_id,
        sku="PIZZA-MARG-L",
        quantity=2,
        price=12.99,
        product_name="Large Margherita Pizza",
    ),
    OrderItem(
        order_id=order_id,
        sku="WINGS-BBQ-10",
        quantity=1,
        price=8.99,
        product_name="BBQ Chicken Wings (10pc)",
    ),
    OrderItem(
        order_id=order_id,
        sku="DRINK-COKE-500",
        quantity=3,
        price=1.50,
        product_name="Coca-Cola 500ml",
        modifications=["Extra ice", "l and l"],
    ),
]

# %%

# Insert order items
try:
    order_items_response = (
        client_ordelo.table("order_item_v2")
        .insert([item.model_dump() for item in order_items])
        .execute()
    )
    print(f"✓ Inserted {len(order_items)} order items for order: {order_id}")
    print(f"Response: {order_items_response.data}")
except Exception as e:
    print(f"✗ Error inserting order_items: {e}")
