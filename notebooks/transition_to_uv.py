# %%
import os
from config import pg_settings

pg_settings.db_uri
# %%

from langgraph.checkpoint.postgres import PostgresSaver

write_config = {"configurable": {"thread_id": "1", "checkpoint_ns": ""}}
read_config = {"configurable": {"thread_id": "1"}}

DB_URI = pg_settings.db_uri

with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    checkpointer.setup()
