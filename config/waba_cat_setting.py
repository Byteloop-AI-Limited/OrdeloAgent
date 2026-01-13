"""
WhatsApp catalog settings and product/inventory helpers for OrdeloAgent.
    . Defines WabaCatalogSettings for Meta catalog access
    . Instantiates waba_cat_settings from environment
    . Provides helper functions to search available items and update product inventory
    . Provides ProductUpdate model for validating SKU to product_id mapping
    . Depends on: pydantic_settings, duckdb, pandas, requests, loguru, json, typing
  Classes:
    . WabaCatalogSettings
    . ProductUpdate
  Functions:
    . search_available_items
    . update_product
    . update_inventory_for_product
    . update_inventory_following_checkout
"""

import json
from typing import Dict, List

# import duckdb as ddb
import pandas as pd
import requests
from loguru import logger
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from aws_setting import ordelo_agent_env


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
        NewClass = type(
            f"{cls.__name__}_{env_prefix}", (cls,), {"model_config": config}
        )
        return NewClass()

    def fetch_all_products_from_meta(
        self, filter_condition: dict = None, sel_cols: List[str] = None
    ):
        logger.info("hitting the products without cache")
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
            response = requests.get(next_page_url, headers=headers, params=params)

            if response.status_code == 200:
                data = response.json()
                all_products.extend(data.get("data", []))
                next_page_url = data.get("paging", {}).get("next")
                params = {}
            else:
                print(f"Error: {response.status_code}")
                print(response.text)
                break

        return all_products


waba_cat_settings = WabaCatalogSettings(**ordelo_agent_env)


def search_available_items(search_item: str) -> List[dict]:
    """
    Search for available items in stock based on a search item in the product description.

    Args:
        search_item (str): The item to search for in product descriptions.

    Returns:
        list: A list of dictionaries containing retailer_id, name, and description
        of products that are in stock and match the search criteria.
    """
    # con = ddb.connect()
    con = "dummy"
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
    # conn = ddb.connect()
    conn = "dummy"
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
        conn.register("cart", pd.DataFrame(cart_list))
        conn.register("product", pd.DataFrame(inventory_list))

        product_rows: List[dict] = conn.execute(query).df().to_dict("records")

        [update_product(row) for row in product_rows]
    finally:
        conn.close()
    return "success"


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
