# %%
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.order_management.food_order_reciept import (
    build_wa_order_reciept_for_rest,
)

# %%

order_id = "PJKU-21"
food_order = FoodOrder.from_order_id(order_id)
rest_header, rest_text = build_wa_order_reciept_for_rest(food_order=food_order)

# %%
rest_header, rest_text

# %%
from config import _async_wa_client as wa
recipient = 447448440754

# %%
await wa.send_text(to=recipient, text=rest_text)
