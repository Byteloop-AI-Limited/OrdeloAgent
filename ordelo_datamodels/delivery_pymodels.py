# %%

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime, date


class DeliveryDetail(BaseModel):
    order_number: str = Field(..., max_length=100)
    vehicle_type: str
    rider_payout: float = 0.0
    distance: float = 0.0
    rest_id: str = Field(..., max_length=50)
    rest_name: str
    rest_lon: float
    rest_lat: float
    rest_address: str
    town: str
    customer_id: str = Field(..., max_length=50)
    customer_name: str
    customer_lon: float
    customer_lat: float
    customer_address: str
    status: str = Field(..., max_length=50)
    dispatch_id: Optional[int] = Field(default=None)
    rider_id: Optional[str] = Field(default=None, max_length=12)

    @property
    def google_maps_url(self) -> str:
        """Generate Google Maps URL for navigation from restaurant to customer."""
        return f"https://maps.google.com/maps?dirflg=d&saddr={self.rest_lat},{self.rest_lon}&daddr={self.customer_lat},{self.customer_lon}"


class DeliverySummary(BaseModel):
    order_number: str = Field(..., max_length=100)
    rest_id: str = Field(..., max_length=12)
    rest_name: str
    rest_lon: float
    rest_lat: float
    rest_address: str
    town: str = Field(..., max_length=255)
    customer_id: str = Field(..., max_length=50)
    customer_name: str
    customer_lon: float
    customer_lat: float
    customer_address: str
    status: str
    rest_confirmation_code: int
    cust_confirmation_code: int
    pickup_time: datetime
    pickup_date: date
    dt: date
    dtts: datetime


class DeliveryDispatch(BaseModel):
    order_number: str = Field(..., max_length=100)
    rider_id: str = Field(..., max_length=12)
    rider_payout: float = 0.0
    distance: float = 0.0
    status: str = Field(..., max_length=50)


""" Test
#%%
elai_basingstoke = RestaurantMaster(
    **{
        "rest_id": "elai_basingstoke", 
        "rest_name": "Elai Basingstoke", 
        "rest_location": "(-1.0845946426613304, 51.262517174733055)", 
        "rest_address": "Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY"}
    )

elai_customer = CustomerMaster(
    **{
        "customer_id": "447448440754",
        "customer_name": "10hith",
        "customer_location": "(0.09590008054155555, 51.35408136953724)",
        "customer_address": "27 Waring Drive, Orpington, BR66DN",
    })

insert_data = {
    "order_number": "10h123456",
    "rider_id": "DRIVER01",
    "rider_payout": 25.50,
    "distance": 10.5,
    "recipient": "RECIPIENT01",
    "status": "Delivered"
}

# elai_customer = CustomerInfo(**insert_data)
_delivery_detail = DeliveryDetail(
    **insert_data, 
    **elai_basingstoke.model_dump(),
    **elai_customer.model_dump()
    )
_delivery_detail.model_dump()
# %%
"""
