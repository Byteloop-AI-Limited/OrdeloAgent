"""
Pydantic models for delivery and dispatch operations
  . Defines DeliveryDetail model for delivery information
  . Defines DeliverySummary model for delivery status tracking
  . Provides Google Maps URL generation for navigation
  . Includes rider and customer location data
  . Supports dispatch status management
  Functions/Classes:
    . DeliveryDetail
    . DeliverySummary
"""

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
