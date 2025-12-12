# %%
# %%
# admin_order_reciept
from config import client_ordelo
from ordelo_datamodels.delivery_pymodels import DeliveryDetail, DeliverySummary


# %%
delivery_summay = (
    client_ordelo.table("delivery_summary")
    .select("*")
    .eq("order_number", "ELAS-OOLX-24")
    .execute()
)
delivery_summary = DeliverySummary(**delivery_summay.data[0])
# delivery_summary = DeliverySummary(**delivery_summay.data[0]["delivery_summary"])

# %%
delivery_detail = (
    client_ordelo.table("delivery_detail")
    .select("*")
    .eq("order_number", "ELAS-OOLX-24")
    .execute()
)
delivery_detail_model = DeliveryDetail(**delivery_detail.data[0])
