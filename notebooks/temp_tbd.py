# %%
from config import client_ordelo

data = (
    client_ordelo.table("delivery_summary")
    .select("rest_confirmation_code")
    .eq("order_number", "WREN-TMCH-28")
    .execute()
).data[0]
# data["rest_confirmation_code"]


# %%

order_number = "WREN-LYTQ-23"

# %%
correct_customer_confirmation_code = (
    client_ordelo.table("delivery_summary")
    .select("cust_confirmation_code")
    .eq("order_number", order_number)
    .execute()
    .data[0]["cust_confirmation_code"]
)
correct_customer_confirmation_code
