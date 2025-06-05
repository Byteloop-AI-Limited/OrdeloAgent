"""
PostgreSQL and Supabase settings for OrdeloAgent.
    . Defines PgSetting for database, REST, and vector store configuration
    . Integrates with Langchain, Supabase, and OpenAI embeddings
    . Provides helpers for connection, headers, and vector search
    . Depends on: pydantic_settings, langchain_postgres, langchain_openai, supabase
"""

# %%
# Move over to https://python.langchain.com/docs/integrations/vectorstores/supabase/#similarity-search-with-score
from pydantic_settings import BaseSettings, SettingsConfigDict
from langchain_postgres.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings
from supabase import create_client, Client, create_async_client, AsyncClient
from psycopg_pool import AsyncConnectionPool
from typing import Optional


class PgSetting(BaseSettings):
    db_uri: str
    vec_db_uri: str
    rest_url: str
    rest_key: str
    service_key: str
    collection_name: str = "elai_embed"
    _async_pool: Optional[AsyncConnectionPool] = None

    @property
    def connection_kwargs(self):
        return {
            "autocommit": True,
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

    model_config = SettingsConfigDict(
        env_prefix="SBASE_", env_file_encoding="utf-8", env_file=None, extra="ignore"
    )

    @property
    def client(self) -> Client:
        return create_client(self.rest_url, self.rest_key)

    async def get_pool(self) -> AsyncConnectionPool:
        if self._async_pool is None:
            self._async_pool = AsyncConnectionPool(
                conninfo=self.db_uri,
                kwargs=self.connection_kwargs,
                min_size=self.pool_kwargs["min_size"],
                max_size=self.pool_kwargs["max_size"],
                max_idle=float(self.pool_kwargs["max_idle"]),
                timeout=float(self.pool_kwargs["timeout"]),
                reconnect_timeout=float(self.pool_kwargs["reconnect_timeout"]),
                open=False,
            )
            await self._async_pool.open()
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


pg_settings = PgSetting()
client_ordelo = pg_settings.client

# pg_settings.connection_kwargs


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
