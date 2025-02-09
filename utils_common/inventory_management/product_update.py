# %% Imports
import pandas as pd 
import duckdb as ddb
import requests 
from config import waba_cat_settings, cat_conn, SKU_PRODUCT_NAME_MAP, SKU_PRODUCT_ID_MAP
from typing import List, Literal
from enum import Enum
import asyncio
import httpx



# %%
cat_conn.execute("select * from elai_meta_cat").df()

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

    with httpx.Client() as client:
        response = client.post(
            url, headers=waba_cat_settings.cat_headers, json=product_row
        )

        if response.status_code == 200:
            print("Success:", response.json())
        else:
            print("Error:", response.status_code, response.text)


# %% update availability

def update_availability(skus: List[str], availability: Literal['out of stock', 'in stock']) -> List[str]:
    """
    Updates inventory for a list of products based on their SKUs. Sets quantity to 0.

    Args:
        skus: A list of SKUs (str).

    Returns:
        A list of strings, each indicating the result of updating a product, 
        e.g., "success" or "failure".
    """
    if availability not in ['out of stock', 'in stock']:
        raise ValueError(f"Invalid availability: {availability}. Must be 'out of stock' or 'in stock'.")


    results = []
    for sku in skus:
        product_id = SKU_PRODUCT_ID_MAP.get(sku)
        
        if not product_id:
            results.append(f"Failure: Product ID not found for SKU: {sku}")
            continue # Skip this product and move to the next one
        
        payload = {
            "product_id": product_id,
            "quantity_to_sell_on_facebook": 0, 
            "availability": availability
        }
        
        try:
           update_product(payload)
           results.append(f"Success: Updated inventory for SKU: {sku}") 
        except Exception as e:
            results.append(f"Failure: Could not update inventory for SKU: {sku}. Error: {e}")
    
    return results

# %% update_inventory_following_checkout
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

# %% Test
"""
# %% referred product
# referred_product
# Message(id='wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAEhgUM0E0NkI1NEU4M0REODM5MjQwMzMA', type=MessageType.TEXT, metadata=Metadata(display_phone_number='447823713944', phone_number_id='434523189754637'), from_user=User(wa_id='447448440754', name='10hith'), timestamp=datetime.datetime(2025, 1, 8, 20, 27, 2), reply_to_message=ReplyToMessage(message_id='wamid.HBgMNDQ3NDQ4NDQwNzU0FQIAERgPcHJvZHVjdF9pbnF1aXJ5AA==', from_user_id='447823713944', referred_product=ReferredProduct(catalog_id='875083621367251', sku='beef_ularthiyathu')), forwarded=False, forwarded_many_times=False, text='G', image=None, video=None, sticker=None, document=None, audio=None, caption=None, reaction=None, location=None, contacts=None, order=None, system=None, error=None)
# %%

update_availability(['aloo_gobi', 'gulab_jamun'], availability='in stock')

# %% Fetch meta_cat on demand
# waba_cat_settings.fetch_all_products_from_meta(sel_cols=[])

# %%
"""