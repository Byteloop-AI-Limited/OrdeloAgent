# %%
from ordelo_datamodels.delivery_dispatch import DeliveryDispatch, RestaurantMaster, CustomerMaster, Point
from decimal import Decimal

# Original input data
insert_data = {
    "order_number": "ORD123456",
    "driver_id": "DRIVER01",
    "driver_payout": 25.50,
    "distance": 10.5,
    "recipient": "RECIPIENT01",
    "rest_id": "REST123",
    "rest_location": "(40.7128,-74.0060)",
    "rest_address": "123 Main St, New York, NY",
    "cust_id": "CUST456",
    "cust_location": "(40.7306,-73.9352)",
    "cust_address": "456 Elm St, New York, NY",
    "dt": "2023-10-01",
    "status": "Delivered"
}

# Parse location strings into tuples
def parse_point(point_str: str) -> dict:
    # Remove parentheses and split by comma
    lat, lon = point_str.strip('()').split(',')
    return {"latitude": float(lat), "longitude": float(lon)}

# Restructure data for our nested models
restaurant_data = {
    "rest_id": insert_data["rest_id"],
    "rest_location": parse_point(insert_data["rest_location"]),
    "rest_address": insert_data["rest_address"]
}

customer_data = {
    "cust_id": insert_data["cust_id"],
    "cust_location": parse_point(insert_data["cust_location"]),
    "cust_address": insert_data["cust_address"]
}

# Create the DeliveryDispatch instance
delivery = DeliveryDispatch(
    order_number=insert_data["order_number"],
    driver_id=insert_data["driver_id"],
    driver_payout=Decimal(str(insert_data["driver_payout"])),  # Convert float to Decimal
    distance=insert_data["distance"],
    recipient=insert_data["recipient"],
    restaurant=RestaurantMaster(**restaurant_data),
    customer=CustomerMaster(**customer_data),
    status=insert_data["status"]
)

# Print the model
print(delivery.model_dump_json(indent=2))
