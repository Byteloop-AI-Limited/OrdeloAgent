"""
Initialize Postgres checkpoint database
    . Sets up the checkpointer using Langgraph's PostgresSaver
    . Reads DB URI from configuration
    . Creates necessary tables for checkpointing
"""

# %% initialize the checkpointer for the first time
from config import pg_settings
from langgraph.checkpoint.postgres import PostgresSaver
# pg_settings.db_uri

with PostgresSaver.from_conn_string(pg_settings.db_uri) as checkpointer:
    checkpointer.setup()
