"""
Query parameter models for WA delivery templates.
    . Validates delivery query parameters used in WhatsApp template URLs
    . Provides defaults for distance, minimum order, and order type values
    . Supplies helper for encoding validated data into URL query strings
  Functions/Classes:
    . RestMenuQueryParams
"""

# %%
from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, Field


class RestMenuQueryParams(BaseModel):
    distance: float = Field(0.5, ge=0, description="Delivery distance in kilometers")
    minimum_order: float = Field(10, ge=0, description="Minimum order amount required")
    order_type: Literal["delivery", "takeaway"] = Field(
        default="delivery", description="Order fulfilment mode"
    )
    thread_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9]+$",
        description="Alphanumeric conversation identifier",
    )
    recipient: str = Field(
        ...,
        pattern=r"^\d{12}$",
        description="Recipient WhatsApp number in E.164 without '+'",
    )

    def to_query_params(self) -> str:
        """Return a URL-encoded query string built from the model data."""
        return urlencode(self.model_dump())


# %%
# params = RestMenuQueryParams(thread_id="Alpha123", recipient="123456789012")
# query = params.to_query_params()  # distance=0.5&minimum_order=10&order_type=delivery&thread_id=Alpha123&recipient=123456789012
# query
