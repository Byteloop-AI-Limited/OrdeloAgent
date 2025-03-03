from typing import Optional
from pydantic import BaseModel, Field
from decimal import Decimal


class RestaurantMaster(BaseModel):
    rest_id: str = Field(..., max_length=50)
    rest_name: str
    rest_lon: float
    rest_lat: float
    rest_address: str
    town: str


class CustomerMaster(BaseModel):
    customer_id: str = Field(..., max_length=50)
    customer_name: str
    customer_lon: float
    customer_lat: float
    customer_address: str