# %%
from config import client_ordelo


# %%
client_ordelo.schema("pgmq_public").rpc(
    "send", {"queue_name": "location_pub", "message": {"food": "pizza"}}
).execute()

# %%
client_ordelo.schema("pgmq_public").rpc(
    "send", {"queue_name": "owntracks", "message": {"food": "pizza"}}
).execute()


# %%
client_ordelo.schema("pgmq_public").table("q_location_pub").select("*").execute()
