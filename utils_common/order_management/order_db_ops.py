# %%
import hashlib
from datetime import datetime
from typing import Dict, List

from dataclasses import asdict
from pydantic import BaseModel, Field, model_validator
import httpx
import psycopg
from pywa.types import Order

from config import project_settings, logger, stripe_settings, SKU_PRODUCT_NAME_MAP
from utils_common.params import filter_dict


# %% define variables 


SALT = project_settings.salt
ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# %% Data models

class FoodOrderModel(BaseModel):
    order_id: str = Field(default=None)
    recipient: str
    thread_id: str
    seq_id: int
    total_amount: float
    order_dt: str = Field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d'))
    order_ts: str = Field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
    order_type: str = "Paid Collection"
    payment_status: str = "awaiting_payment"

    @model_validator(mode="after")
    def generate_order_id(self) -> "FoodOrderModel":
        if not self.order_id:
            self.order_id = self._create_order_number() + '-' + str(self.seq_id)
        return self


    def _create_order_number(self) -> str:
        number = self.recipient[-4:]
        """Encodes a 4-digit number string into a 4-character string."""
        if not len(number) == 4 or not number.isdigit():
            raise ValueError("Number must be a 4-digit string")
        
        salted_number = f"{number}{SALT}{self.order_dt}"
        hashed_number = hashlib.sha256(salted_number.encode()).hexdigest()
        
        encoded_chars: str = ""
        for i in range(4):
            index = int(hashed_number[i*2:i*2+2], 16) % len(ALPHABET)
            encoded_chars += ALPHABET[index]
        return encoded_chars.upper()
    

class OrderItem(BaseModel):
    order_id: str
    product_name: str
    quantity: int
    price: float


# %% define funcs

def get_order_total(wa_order: Order):
    order_total: float = 0.0
    for product in wa_order.products:
        order_total += product.price
    return order_total


async def create_order_items_from_order(wa_order: Order, order_id: str, sku_nam_map: Dict[str, str] = SKU_PRODUCT_NAME_MAP) -> List[OrderItem]:
    """
    Transforms a pywa Order object into a list of OrderItem objects, enriching each item with product name and order id.

    Args:
        order: The pywa Order object containing product details.
        order_id: The ID of the order to associate with the created order items.
        sku_nam_map: A dictionary mapping SKU codes to product names. Defaults to the global sku_name_map.

    Returns:
        A list of OrderItem objects, each representing a product in the order.
    """
    order_items: List[OrderItem] = []

    for product in wa_order.products:
        _dict = asdict(product)
        _dict['product_name'] = sku_nam_map.get(product.sku)
        _dict['order_id'] = order_id
        _order_item = OrderItem(**_dict)
        order_items.append(_order_item)
    return order_items



async def create_order_summary(order_items: List[dict]) -> Dict:
    """
    Creates an order summary which is also a payload for creating a Stripe Payment Intent.

    This function takes a list of order details (dictionaries), extracts relevant
    information, and formats it into a dictionary suitable for use in a Stripe API call.

    Args:
        order_items: A list of dictionaries, where each dictionary represents an
        order item and includes order-level information.

    Returns:
        A dictionary representing the payload for a Stripe Payment Intent.
        It includes the order ID, type, payment status, recipient, thread ID,
        a list of items (product name, price, quantity), and the currency.
    """
    food_order_data: dict = filter_dict(
        [order_items[0]],
        select_cols=['order_id', 'order_type', 'payment_status', 'recipient', 'thread_id']
        )[0]

    order_items_data: List[dict] = filter_dict(
        order_items, 
        select_cols=['product_name', 'price', 'quantity']
        )

    order_summary_dict: dict = {
        **food_order_data,    
        "items": order_items_data,
        "currency": "GBP"
    }
    
    return order_summary_dict


async def process_order_into_db(
    pool, 
    recipient: str, 
    thread_id: str, 
    wa_order: Order
):
    order_handler = OrderHandler(pool)
    # get seq_id for the day
    seq_id = await order_handler.get_seq_num()
    
    # create food_order
    food_order = {
        "recipient": recipient,
        "total_amount": get_order_total(wa_order), 
        "thread_id" : thread_id,
        "seq_id": seq_id
    }
    food_order = FoodOrderModel(**food_order)
    order_id = food_order.order_id

    if await order_handler.create_food_order(food_order) \
        and await order_handler.insert_order_items(wa_order, order_id=food_order.order_id):
        logger.info(f"Order {order_id} inserted into db")
        return order_id
    else:
        return False


async def create_order_summary_from_db(
    pool,  
    order_id: str
) -> dict:
    order_handler = OrderHandler(pool)
    order_items: List[dict] = await order_handler.get_order_items(order_id=order_id)

    food_order_data: dict = filter_dict(
        [order_items[0]],
        select_cols=['order_id', 'order_type', 'payment_status', 'recipient', 'thread_id']
        )[0]

    order_items_data: List[dict] = filter_dict(
        order_items, 
        select_cols=['product_name', 'price', 'quantity']
        )

    order_summary_dict: dict = {
        **food_order_data,    
        "items": order_items_data,
        "currency": "GBP"
    }

    return order_summary_dict

    

# %%

async def get_stripe_payment_link(pool, order_id: str):
    """
    Generates a Stripe payment link for a given order.

    Args:
        order_details: A list of dictionaries containing order details.

    Returns:
        A string representing the Stripe payment link URL.
    """
    order_summary: dict = await create_order_summary_from_db(pool, order_id=order_id)

    payment_intent_url = stripe_settings.generate_payment_intent_url(
        order_id=order_summary.get('order_id'), 
        thread_id=order_summary.get('thread_id')
        )

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_intent_url, 
                json=order_summary, 
                headers=stripe_settings.headers
                )
            res.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return res.json()['url']
        except httpx.HTTPError as e:
            print(f"Error during payment intent creation: {e}")
            return None


# %%
class OrderHandler:
    def __init__(self, pool):
        self.pool = pool

    async def get_seq_num(self):
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        await cur.execute(
                            """
                            SELECT * FROM get_next_daily_seq(%s)
                            """,
                            (datetime.now().strftime('%Y-%m-%d'),),
                        )
                        result = await cur.fetchone()
                    return result['get_next_daily_seq']
            except psycopg.Error as e:
                # Handle exceptions as needed
                print(f"Error in get_active_thread: {e}")
                raise

    async def get_order_items(self, order_id: str):
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        await cur.execute(
                            """
                            SELECT 
                                oi.product_name,
                                oi.price,
                                oi.quantity,
                                fo.order_id,
                                fo.order_type,
                                fo.payment_status,
                                fo.recipient,
                                fo.thread_id
                            FROM OrderItem oi
                            INNER JOIN FoodOrder fo 
                            ON oi.order_id = fo.order_id
                            where fo.order_id=%s
                            """,
                            (order_id,),
                        )
                        result = await cur.fetchall()
                    return result
            except psycopg.Error as e:
                # Handle exceptions as needed
                print(f"Error in order items: {e}")
                raise
    
    async def create_food_order(self, food_order: FoodOrderModel):
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    values = tuple(food_order.model_dump().values())
                    cols = FoodOrderModel.model_fields.keys()
                    await cur.execute(
                        f"""
                        INSERT INTO 
                        FoodOrder(
                            {','.join(cols)}
                            )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        values,
                    )
                return True
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in create_food_order: {e}")
            raise

    async def update_order(self, order_id: str):
            try:
                async with self.pool.connection() as conn:
                    async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        await cur.execute(
                            """
                            UPDATE FoodOrder
                            SET 
                                payment_status=%s,
                                order_ts=%s
                            WHERE order_id=%s
                            """,
                            (
                                'payment_complete',
                                datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                                order_id
                            ),
                        )
                    return True
            except psycopg.Error as e:
                # Handle exceptions as needed
                print(f"Error in get_active_thread: {e}")
                raise

    async def insert_order_items(self, order: Order, order_id: str):
        """
        Insert all order items into database

        1. Create order items for insert
        2. Insert all order items into database
        """
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    columns = tuple(OrderItem.model_fields.keys())
                    # 1. Create order items for insert
                    order_items: List[OrderItem] = await create_order_items_from_order(order, order_id)
                    
                    order_items_tuples: List[tuple] = [
                        tuple(order_item.model_dump().values()) 
                        for order_item in 
                        order_items
                    ]

                    query = f"""
                        INSERT INTO OrderItem (
                            {','.join(columns)}
                        )
                        VALUES ({', '.join(['%s'] * len(columns))})
                        """
                    # 2. Insert all order items into database
                    await cur.executemany(query, order_items_tuples)
                return True
        except psycopg.Error as e:
            # Handle exceptions as needed
            print(f"Error in create_food_order: {e}")
            raise

""" todo
# %% test Run

_order = Order(
    catalog_id='875083621367251', 
    products=(Product(sku='chilli_chicken', quantity=1, price=9.95, currency='GBP'), Product(sku='aloo_gobi', quantity=2, price=9.95, currency='GBP'), Product(sku='apple_and_mango_smoothie', quantity=1, price=5.95, currency='GBP'))
    , 
    text=''
    )
# below fails
_order = Order(catalog_id='875083621367251', products=(Product(sku='mango_lassi', quantity=1, price=4.5, currency='GBP'),), text='')


async with AsyncConnectionPool(
    conninfo=pg_settings.db_uri,
    max_size=20,
    kwargs=pg_settings.connection_kwargs,
) as pool:
    # _order
    response = await create_order_items_from_order(_order, order_id="123", sku_nam_map=SKU_PRODUCT_NAME_MAP)
    order_handler = OrderHandler(pool)
    order_id = await process_order_into_db(pool, "447424334783", "123", _order)
    order_summary = await create_order_summary_from_db(pool, order_id=order_id)
    stripe_link = await get_stripe_payment_link(pool, order_id=order_id)



# %%
"""