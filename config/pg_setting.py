"""
Manages PostgreSQL and Supabase settings for the OrdeloAgent application.
    . Defines the `PgSetting` class using `pydantic_settings` for loading database URIs, Supabase REST URLs, API keys, and vector store configurations from environment variables.
    . Initializes and provides access to a `supabase.Client` and `supabase.AsyncClient` for interacting with Supabase services.
    . Manages an `psycopg_pool.AsyncConnectionPool` for direct asynchronous PostgreSQL database connections. This pool is intended to be managed by the FastAPI application's lifespan events.
    . Configures and provides a `langchain_postgres.vectorstores.PGVector` instance for vector similarity searches, using OpenAI embeddings.
    . Includes helper properties for Supabase headers, REST endpoints, and connection/pool keyword arguments.
    . Dependencies: `pydantic_settings`, `langchain_postgres`, `langchain_openai`, `supabase`, `psycopg_pool`.
"""

# %%
# Move over to https://python.langchain.com/docs/integrations/vectorstores/supabase/#similarity-search-with-score
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_postgres.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings
from supabase import create_client, Client, create_async_client, AsyncClient
from psycopg_pool import AsyncConnectionPool
from typing import Optional
from loguru import logger
from aws_setting import ordelo_agent_env
from pydantic import Field

ordelo_agent_env


# %%
class PgSetting(BaseSettings):
    db_uri: str = Field(..., alias="sbase_ordelo_db_uri")
    vec_db_uri: str = Field(..., alias="sbase_ordelo_vec_db_uri")
    rest_url: str = Field(..., alias="sbase_ordelo_rest_url")
    rest_key: str = Field(..., alias="sbase_ordelo_rest_key")
    service_key: str = Field(..., alias="sbase_ordelo_service_key")
    collection_name: str = "elai_embed"
    _async_pool: Optional[AsyncConnectionPool] = None

    @property
    def connection_kwargs(self):
        return {
            "autocommit": False,
            "prepare_threshold": None,
            "connect_timeout": 10,  # Connection timeout in seconds
            "keepalives": 1,  # Enable TCP keepalives
            "keepalives_idle": 60,  # Seconds of inactivity before sending keepalive
            "keepalives_interval": 10,  # Seconds between keepalives
            "keepalives_count": 5,  # Number of keepalives before considering connection dead
        }

    @property
    def pool_kwargs(self):
        return {
            "min_size": 1,  # Only ever open 1 connection at a time in lambda
            "max_size": 5,  # Maximum connections in pool
            "max_idle": 30,  # if lambda is idles > 30s, automatically close idle sockets
            "timeout": 20,  # when aquiring, wait up to 20s before throwing "timeout"
            "reconnect_timeout": 10,  # If socket is broken, attempts to reconnect automatically
            "open": False,  # We'll open it explicitly
        }

    @property
    def headers(self):
        return {
            # "Authorization": f"Bearer {self.rest_key}",
            "apiKey": self.service_key,
            "Accept": "application/json",
            "Authorization": f"Bearer {self.rest_key}",
            "Content-Type": "application/json",
        }

    @property
    def service_headers(self):
        return {
            # "Authorization": f"Bearer {self.rest_key}",
            "apiKey": self.service_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @property
    def rest_endpoint_function(self):
        return f"{self.rest_url}/rest/v1/rpc/search_documents"

    @property
    def rest_endpoint(self):
        return f"{self.rest_url}/rest/v1"

    model_config = SettingsConfigDict(extra="allow")

    @property
    def client(self) -> Client:
        return create_client(self.rest_url, self.rest_key)

    async def get_pool(self) -> AsyncConnectionPool:
        # If pool doesn't exist, or if it exists but was closed
        if self._async_pool is None or self._async_pool.closed:
            # Optional: Add logging here if you want to know when a closed pool is being recreated
            logger.info("AsyncConnectionPool is None or closed, creating a new one.")
            self._async_pool = AsyncConnectionPool(
                conninfo=self.db_uri,
                kwargs=self.connection_kwargs,
                min_size=self.pool_kwargs["min_size"],
                max_size=self.pool_kwargs["max_size"],
                max_idle=float(self.pool_kwargs["max_idle"]),
                timeout=float(self.pool_kwargs["timeout"]),
                reconnect_timeout=float(self.pool_kwargs["reconnect_timeout"]),
                open=False,  # Initialize with open=False
            )
            await self._async_pool.open()  # Explicitly open it
        return self._async_pool

    @property
    def async_client(self) -> AsyncClient:
        return create_async_client(self.rest_url, self.rest_key)

    @property
    def vector_store(self):
        return PGVector(
            embeddings=OpenAIEmbeddings(model="text-embedding-3-large"),
            collection_name=self.collection_name,
            connection=self.vec_db_uri,
            use_jsonb=True,
        )


pg_settings = PgSetting(**ordelo_agent_env)
client_ordelo = pg_settings.client


# %% Similarity search
# metadata_filter = {"id": {"$eq": "sweet_lassi"}}
# results = vector_store.similarity_search_with_score(
#     query="mutton starters",
#     k=7,
#     )
# for doc, score in results:
#     print(f"* [SIM={score:3f}] {doc.page_content} [{doc.metadata}]")


# %% AS retriever

# retriever = vector_store.as_retriever(
#     search_type="mmr",
#     search_kwargs={"k": 30, "fetch_k": 7, "lambda_mult": 0.5}
# )
# retriever.invoke("mutton starters")

# %% delete collection
# vector_store.delete_collection()

# %%
# client_ordelo.table("delivery_detail").select("*").execute()
