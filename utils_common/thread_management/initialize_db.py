"""
Database initialization script for LangGraph checkpointer
  . Sets up PostgreSQL schema for conversation state storage
  . Initializes LangGraph PostgresSaver checkpointer
  . One-time setup script for database tables
  Functions/Classes:
    . checkpointer (setup execution)
"""

# %% initialize the checkpointer for the first time
from config import pg_settings
from langgraph.checkpoint.postgres import PostgresSaver
# pg_settings.db_uri

with PostgresSaver.from_conn_string(pg_settings.db_uri) as checkpointer:
    checkpointer.setup()