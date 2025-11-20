"""
Pricing logic and calculations for orders and delivery
  . Calculates minimum order values based on location
  . Computes final order values including fees
  . Calls pricing microservice API for delivery options
  . Extracts delivery fee messages for customers
  . Handles restaurant and customer location data
  Functions/Classes:
    . get_min_order_value
    . get_final_order_value
"""

# %%
from config import ms_settings
from config.params import REST_MASTER
import requests


# %%
def get_min_order_value(order_number: str, cust_lat: float, cust_lon: float):
    payload = {
        "order_number": order_number,
        "total_food_value": 0,
        "restaurant_latitude": REST_MASTER.lat,
        "restaurant_longitude": REST_MASTER.lon,
        "customer_latitude": cust_lat,
        "customer_longitude": cust_lon,
    }
    url = ms_settings.pricing_url

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers)
    response_json = response.json()

    message = ""
    for option in response_json["delivery_options"]:
        if option["vehicle_type"] == "car":
            message += option["message"]

    return message


# %%
def get_final_order_value(
    order_number: str, cust_lat: float, cust_lon: float, total_food_value: float
):
    # ToDo
    payload = {
        "order_number": order_number,
        "total_food_value": total_food_value,
        "restaurant_latitude": REST_MASTER.lat,
        "restaurant_longitude": REST_MASTER.lon,
        "customer_latitude": cust_lat,
        "customer_longitude": cust_lon,
    }
    url = ms_settings.pricing_url

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        return response.status_code, response.text
    response_json = response.json()

    option = {}
    for option in response_json["delivery_options"]:
        if option["vehicle_type"] == "car":
            option = option
            break

    return option


"""
# %% Test

payload = {
    "order_number": "QPRX-11",
    "total_food_value": 64,
    "restaurant_latitude": ELAIB.lat,
    "restaurant_longitude": ELAIB.lon,
    "customer_latitude": 51.3820,
    "customer_longitude": 0.0920,
}

url = ms_settings.pricing_url

headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload, headers=headers)
response_json = response.json()

response_json
# %%
"""
