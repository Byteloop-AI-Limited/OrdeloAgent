"""
Product catalog configuration and connection for OrdeloAgent.
    . Defines CatConSettings for managing catalog data
    . Initializes DuckDB connection for catalog storage
    . Supports loading catalog from Google Sheets
    . Enables item search and catalog management
    . Depends on: pydantic_settings, duckdb
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
import duckdb as ddb


# %%
class CatConSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    def init_local_catalog(self, conn: ddb.DuckDBPyConnection):
        """Initialize the local catalog from Google Sheets."""

        pass


cat_con_settings = CatConSettings()

# initialize cat_conn
cat_conn = ddb.connect()
