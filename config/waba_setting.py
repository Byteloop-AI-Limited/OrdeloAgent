"""
WhatsApp Business API settings and catalog configuration for OrdeloAgent.
    . Defines WabaBusinessSettings and WabaCatalogSettings for WhatsApp integration
    . Handles authentication, API tokens, and private key management
    . Provides methods for WhatsApp client instantiation (sync and async)
    . Includes inventory/product update helpers and Facebook Graph API integration
    . Depends on: pydantic_settings, pywa_async, pywa, duckdb, pandas, requests, loguru, base64, os
"""

# %%

import json
from typing import Dict, List
from loguru import logger
import duckdb as ddb
import pandas as pd
import requests
import base64
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pywa_async import WhatsApp
from pywa import WhatsApp as WhatsAppSync
from aws_setting import ordelo_agent_env

# from config.logger_setting import logger
import os

# %%

# NAMESPACE = "bloopappreview"
# NAMESPACE = "vango"
NAMESPACE = "bloop"


class WabaBusinessSettings(BaseSettings):
    account_id: str = Field(..., alias=f"{NAMESPACE}_waa_account_id")
    token: str = Field(..., alias=f"{NAMESPACE}_waa_token")
    phone_id: int = Field(..., alias=f"{NAMESPACE}_waa_phone_id")
    callback_url: str = Field(..., alias=f"{NAMESPACE}_waa_callback_url")
    verify_token: str = Field(..., alias=f"{NAMESPACE}_waa_verify_token")
    app_id: str = Field(..., alias=f"{NAMESPACE}_waa_app_id")
    app_secret: str = Field(..., alias=f"{NAMESPACE}_waa_app_secret")
    private_key_password: str = Field(
        ..., alias=f"{NAMESPACE}_waa_private_key_password"
    )
    private_key_base64: str = Field(..., alias=f"{NAMESPACE}_waa_private_key_base64")

    model_config = SettingsConfigDict(extra="ignore")

    def create_wa(self, app=None):
        kwargs = {
            "business_account_id": self.account_id,
            "token": self.token,
            "verify_token": self.verify_token,
            "phone_id": self.phone_id,
        }
        if app is not None:
            kwargs["server"] = app
        return WhatsApp(**kwargs)

    def create_wa_sync(self):
        return WhatsAppSync(
            token=self.token,
            business_account_id=self.account_id,
            verify_token=self.verify_token,
            phone_id=self.phone_id,
        )

    @property
    def private_key(self) -> str:
        """Get the private key from the environment variable"""
        try:
            # Decode the base64 string
            decoded_bytes = base64.b64decode(self.private_key_base64)
            # Convert bytes to string (assuming PEM format needs string)
            processed_key = decoded_bytes.decode("utf-8")
            return processed_key
        except base64.binascii.Error as e:
            logger.error(f"Failed to decode base64 private key: {e}")
            return ""
        except Exception as e:
            logger.error(f"Error processing base64 private key: {e}")
            return ""

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    # @property
    # def private_key(self) -> str:
    #     """Get the private key from the config/temp_keys folder"""

    #     # Construct the path to the private key file
    #     base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    #     key_path = os.path.join(base_dir, "config", "temp_cache", "test_cde")

    #     try:
    #         with open(key_path, "r") as f:
    #             return f.read()
    #     except FileNotFoundError:
    #         logger.warning(f"Private key file not found at: {key_path}")
    #         return ""
    #     except Exception as e:
    #         logger.warning(f"Error reading private key file: {e}")
    #         return ""


# %%
waba_business_settings = WabaBusinessSettings(**ordelo_agent_env)
# waba_business_settings = WabaBusinessSettings.with_env_prefix("BLOOP_WAA_")
_async_wa_client = waba_business_settings.create_wa()
_sync_wa_client = waba_business_settings.create_wa_sync()
waba_business_settings.phone_id, waba_business_settings.account_id

# %%
# _sync_wa_client.get_business_phone_number().webhook_configuration

# _sync_wa_client.override_waba_callback_url(
#     callback_url="https://agent.ordelo.app/",
#     # callback_url="https://rider-agent.ordelo.app/",
#     verify_token="123456",
#     waba_id=waba_business_settings.account_id,
# )

# %%

NAMESPACE = "waba_provider"


class WabaProviderSettings(BaseSettings):
    app_id: str = Field(..., alias=f"{NAMESPACE}_app_id")
    app_secret: str = Field(..., alias=f"{NAMESPACE}_app_secret")
    configuration_id: str = Field(..., alias=f"{NAMESPACE}_configuration_id")
    graph_api_version: str = Field(..., alias=f"{NAMESPACE}_graph_api_version")
    pin: str = Field(..., alias=f"{NAMESPACE}_pin")
    token: str = Field(..., alias=f"{NAMESPACE}_token")
    business_portfolio_id: str = Field(..., alias=f"{NAMESPACE}_business_protfolio_id")

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    @property
    def graph_api_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}"

    # @classmethod
    # def with_env_prefix(cls, env_prefix):
    #     config = SettingsConfigDict(
    #         env_prefix=env_prefix, env_file_encoding="utf-8", extra="ignore"
    #     )
    #     # Create a new subclass with the updated config
    #     NewClass = type(
    #         f"{cls.__name__}_{env_prefix}", (cls,), {"model_config": config}
    #     )
    #     return NewClass()


# %%

waba_provider_settings = WabaProviderSettings(**ordelo_agent_env)
waba_provider_settings


# %%
class WabaCatalogSettings(BaseSettings):
    account_id: str = Field(..., alias="bloop_waa_account_id")
    cat_token: str = Field(..., alias="bloop_waa_cat_token")
    cat_id: str = Field(..., alias="bloop_waa_cat_id")
    cat_link: str = Field(..., alias="bloop_waa_cat_link")
    feed_id: str = Field(..., alias="bloop_waa_feed_id")
    feed_url: str = Field(..., alias="bloop_waa_feed_url")
    admins: List[str] = []

    model_config = SettingsConfigDict(extra="allow")

    @property
    def cat_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cat_token}",
        }

    @classmethod
    def with_env_prefix(cls, env_prefix):
        config = SettingsConfigDict(
            env_prefix=env_prefix, env_file_encoding="utf-8", extra="ignore"
        )
        # Create a new subclass with the updated config
        NewClass = type(
            f"{cls.__name__}_{env_prefix}", (cls,), {"model_config": config}
        )
        return NewClass()

    def fetch_all_products_from_meta(
        self, filter_condition: dict = None, sel_cols: List[str] = None
    ):
        logger.info("hitting the products without cache")
        # Define the base endpoint URL
        base_url = f"https://graph.facebook.com/v21.0/{self.cat_id}/products"
        headers = self.cat_headers
        filter_json = json.dumps(filter_condition or {})
        _default_sel_cols = [
            "name",
            "quantity_to_sell_on_facebook",
            "availability",
            "id",
            "retailer_id",
            "price",
            "description",
            "url",
            "image_url",
            "condition",
            "currency",
            "product_id",
        ]

        # Initialize parameters and storage for all products
        params = {
            "fields": f"{_default_sel_cols}",
            "filter": filter_json,
        }

        if sel_cols is not None:
            params = {
                "fields": f"{sel_cols}",
                "filter": filter_json,
            }

        all_products = []
        next_page_url = base_url

        while next_page_url:
            # Make the GET request
            response = requests.get(next_page_url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                # Append current page's products to the list
                all_products.extend(data.get("data", []))
                # Check for the next page URL
                next_page_url = data.get("paging", {}).get("next")
                # Clear params after the first request to avoid duplication in subsequent requests
                params = {}
            else:
                print(f"Error: {response.status_code}")
                print(response.text)
                break

        return all_products


waba_cat_settings = WabaCatalogSettings(**ordelo_agent_env)


# %%timeit
# waba_cat_setting.fetch_products()
def search_available_items(search_item: str) -> List[dict]:
    """
    Search for available items in stock based on a search item in the product description.

    Args:
        search_item (str): The item to search for in product descriptions.

    Returns:
        list: A list of dictionaries containing retailer_id, name, and description
        of products that are in stock and match the search criteria.
    """
    con = ddb.connect()
    in_stock_products = waba_cat_settings.fetch_products(
        filter_condition={"availability": {"eq": "in stock"}}
    )
    con.register("inStockProducts", pd.DataFrame(in_stock_products))

    filtered_records = (
        con.execute(
            f"""
        SELECT 
            retailer_id, name, description 
        FROM inStockProducts 
        WHERE LOWER(description) LIKE '%{search_item.lower()}%'
        """
        )
        .df()
        .to_dict("records")
    )

    con.close()
    return filtered_records


# %%
def update_product(product_row: dict):
    """
    Updates a product on Facebook's Graph API using the provided product data.

    :param product_row: A dictionary containing product information.
                        The dictionary can include a 'product_id' key which is used
                        to identify the product to be updated. If 'product_id' is not
                        present, the update will proceed without targeting a specific
                        product.
    :raises ValueError: If 'product_id' is present in product_row but is None.

    This function sends a POST request to the Graph API to update the product.
    If the update is successful, it prints the response JSON. Otherwise,
    it prints an error message with the status code and response text.
    """
    product_id = product_row.get("product_id")
    url = (
        f"https://graph.facebook.com/v21.0/{product_id}"
        if product_id
        else "https://graph.facebook.com/v21.0/"
    )
    response = requests.post(
        url, headers=waba_cat_settings.cat_headers, json=product_row
    )

    if response.status_code == 200:
        print("Success:", response.json())
    else:
        print("Error:", response.status_code, response.text)


def update_inventory_for_product(sku: str, quantity_to_sell_on_facebook: int) -> str:
    product_id = waba_cat_settings.sku_product_id_map.get(sku)

    payload = {
        "product_id": product_id,
        "quantity_to_sell_on_facebook": quantity_to_sell_on_facebook,
    }

    update_product(payload)
    return "success"


def update_inventory_following_checkout(
    cart_list: List[dict], inventory_list: List[dict]
) -> str:
    """
    Generates a product update payload based on the provided cart and inventory lists.

    This function connects to a DuckDB database, runs a query to determine the product
    updates required based on the quantities in the cart compared to the available inventory.
    It calculates the quantity to sell on Facebook for each product and then updates those
    products on Facebook's Graph API.

    :param cart_list: A list of dictionaries representing the cart items,
                      where each dictionary should contain at least the 'sku' key.
    :param inventory_list: A list of dictionaries representing the available inventory,
                           where each dictionary should include the product details,
                           particularly the 'retailer_id' and 'quantity_to_sell_on_facebook'.
    :return: A string indicating the result of the operation. Will return "success"
             if the updates are processed.
    """
    # Create a new DuckDB connection for this request
    conn = ddb.connect()
    print("updating update_inventory_following_checkout")
    query = """
    select 
        id as product_id,
        prod.retailer_id, 
        CASE 
            WHEN quantity_to_sell_on_facebook - cart.quantity < 0 THEN 0
            ELSE quantity_to_sell_on_facebook - cart.quantity
        END AS quantity_to_sell_on_facebook  
    FROM product prod
    INNER JOIN cart cart
    ON prod.retailer_id = cart.sku
    """
    try:
        # Register DataFrames as tables in this connection
        conn.register("cart", pd.DataFrame(cart_list))
        conn.register("product", pd.DataFrame(inventory_list))

        # Execute your query (ensure it uses 'cart' and 'product' as table names)
        product_rows: List[dict] = conn.execute(query).df().to_dict("records")

        # Process the product rows
        [update_product(row) for row in product_rows]
    finally:
        # Ensure the connection is closed after processing
        conn.close()
    return "success"


# %%


class ProductUpdate(BaseModel):
    sku: str
    quantity: int
    product_id: str = None

    def __init__(self, **data):
        super().__init__(**data)
        sku = data.get("sku")
        if sku is None:
            raise ValueError("SKU must be provided")
        self.product_id = waba_cat_settings.sku_product_id_map.get(sku)
        if self.product_id is None:
            raise ValueError(f"No product_id found for sku: {sku}")
