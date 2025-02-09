# %% 
from pywa.types import Product, Order
from dataclasses import asdict
from typing import List


_order = Order(
    catalog_id='875083621367251', 
    products=(Product(sku='chilli_chicken', quantity=1, price=9.95, currency='GBP'), Product(sku='aloo_gobi', quantity=2, price=9.95, currency='GBP'), Product(sku='apple_and_mango_smoothie', quantity=1, price=5.95, currency='GBP'))
    , 
    text=''
    )

asdict(_order)

# %%

# %%
_order.products

# %%
from config import waba_cat_settings

# waba_cat_settings.fetch_products()
sku_name_map = waba_cat_settings.get_sku_name_map()
sku_name_map

# %%
order_items: List[dict] = []
for product in _order.products:
    _dict = asdict(product)
    _dict['product_name'] = sku_name_map.get(product.sku)
    order_items.append(_dict)


# %%
order_items

# %%
import requests 
from config import stripe_settings
order_id="abcg-21"
thread_id="123"

payment_intent_url = stripe_settings.generate_payment_intent_url(order_id=order_id, thread_id=thread_id)

payload = {
    "order_id": "exmp-21",
    "recipient": "447448440754",
    "currency": "GBP",
    "order_type": "Paid Collection",
    "items":[
        {
            "product_name": "burger",
            "price": 5.5,
            "quantity": 2
        },
        {
            "product_name": "burger",
            "price": 5.5,
            "quantity": 2
        }
    ]
}

res = requests.post(payment_intent_url, json=payload, headers=stripe_settings.headers)

res.text
