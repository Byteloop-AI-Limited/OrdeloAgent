# %%
"""
CatConSettings class to manage a product catalog, 
including initializing it from a data source and searching for items. 
It also initializes a DuckDB connection and attempts to load the catalog from Google Sheets) and enabling item searches. 
It initializes a DuckDB connection and attempts to load the catalog data.
"""


from pydantic_settings import BaseSettings, SettingsConfigDict
import duckdb as ddb
import pandas as pd
from config.google_setting import g_client
from config import project_settings
from config.waba_setting import waba_cat_settings
import time

# %% define data sources
elai_meta_cat_pdf = pd.read_parquet(f"{project_settings.project_root}/data/meta_cat.parquet")
elai_cat_pdf = pd.read_parquet(f"{project_settings.project_root}/data/elai_cat_pdf.parquet")

# %% for production run

# elai_meta_cat_pdf: pd.DataFrame = pd.DataFrame(waba_cat_settings.fetch_all_products_from_meta())

# sheet = g_client.open("elai_takeaway_menu").sheet1  # Assuming you're working with the first sheet
# elai_cat_pdf = pd.DataFrame(sheet.get_all_records())

# %%
class CatConSettings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore"
    )

    def init_local_catalog(self, conn:ddb.DuckDBPyConnection):
        """Initialize the local catalog from Google Sheets."""

        CATALOG_READ_QUERY = """
        CREATE OR REPLACE TABLE elai_cat AS
        SELECT
            *,
            google_product_category as food_type,
            CAST(REPLACE(price,' GBP', '') AS DOUBLE) AS price_val,
            CASE WHEN 'C' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'is_crustacean',
            CASE WHEN 'D' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'contains_dairy',
            CASE WHEN 'E' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'contains_eggs',
            CASE WHEN 'F' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'contains_fish',
            CASE WHEN 'G' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'gluten_present',
            CASE WHEN 'N' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'nuts_present',
            CASE WHEN 'V' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'is_vegetarian',
            CASE WHEN 'VE' IN SPLIT(custom_label_0, ' ') THEN TRUE ELSE FALSE END AS 'is_vegan'
        FROM elai_cat_pdf
        """
        conn.execute(CATALOG_READ_QUERY)

        META_CAT_QUERY = """
        CREATE OR REPLACE TABLE elai_meta_cat AS
        SELECT
            *
        FROM elai_meta_cat_pdf
        """
        conn.execute(META_CAT_QUERY)

        return True


    def search_item(self, conn:ddb.DuckDBPyConnection, search_item: str):
        search_item_formatted = search_item.lower()
        _cat_search_query = f"""
        SELECT
            google_product_category AS products_title,
            LIST(id) AS sky
        FROM elai_cat 
        WHERE id like '%{search_item_formatted}%' OR LOWER(title) LIKE '%{search_item_formatted}%'
        GROUP BY 1
        """
        search_results = conn.execute(_cat_search_query).fetchall()
        return search_results


cat_con_settings = CatConSettings()

# initialize cat_conn
cat_conn = ddb.connect()

# attempt google connection a few times
for _ in range(3):
    try:
        cat_con_settings.init_local_catalog(cat_conn)
        break  # Exit loop if successful
    except Exception as e:
        time.sleep(1)  # Wait a bit before retrying
        # Handle the exception if necessaryss


# %% Create the sku and product mapping
_sku_name_mapping_query = """
SELECT
    retailer_id, 
    name
FROM elai_meta_cat
"""
sku_map_raw_rows = cat_conn.execute(_sku_name_mapping_query).df().to_dict('records')
SKU_PRODUCT_NAME_MAP = {}
for row in sku_map_raw_rows:
    SKU_PRODUCT_NAME_MAP[row['retailer_id']] = row['name']


# %% 
_sku_id_mapping_query = """
SELECT
    retailer_id, 
    id
FROM elai_meta_cat
"""
sku_map_raw_rows = cat_conn.execute(_sku_id_mapping_query).df().to_dict('records')
SKU_PRODUCT_ID_MAP = {}
for row in sku_map_raw_rows:
    SKU_PRODUCT_ID_MAP[row['retailer_id']] = row['id']


