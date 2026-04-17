# %%
from config import client_ordelo
# %%

result = (
    client_ordelo.table("rider_master")
    .select("rider_id, rider_name")
    .eq("town", "Salisbury")
    .execute()
    .data
)
print(result)
