# %%
"""
CatConSettings class to manage a product catalog, 
including initializing it from a data source and searching for items. 
It also initializes a DuckDB connection and attempts to load the catalog from Google Sheets) and enabling item searches. 
It initializes a DuckDB connection and attempts to load the catalog data.
"""


from pydantic_settings import BaseSettings, SettingsConfigDict
import duckdb as ddb

# %%
class CatConSettings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore"
    )

    def init_local_catalog(self, conn:ddb.DuckDBPyConnection):
        """Initialize the local catalog from Google Sheets."""

        pass

cat_con_settings = CatConSettings()

# initialize cat_conn
cat_conn = ddb.connect()