"""Typed contracts for the durable on-demand WhatsApp location flow.

These models deliberately contain no arbitrary rider identifier or coordinates
supplied by an LLM. Ordelo resolves those values from the delivery assignment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlsplit


LocationRequester = Literal["customer", "restaurant_admin"]
LocationSource = Literal["whatsapp_current", "restaurant_confirmation"]
LocationRequestStatus = Literal[
    "location_available", "rider_prompted", "waiting_for_rider"
]


class WaLocationDemand(BaseModel):
    """One authorised caller requesting a location for one delivery order."""

    rest_ref: str = Field(min_length=1, max_length=20)
    order_number: str = Field(min_length=1, max_length=100)
    location_requested_by: LocationRequester
    requester_id: str = Field(min_length=1, max_length=50)
    callback_url: str = Field(min_length=1, max_length=2048)
    idempotency_key: str | None = Field(default=None, max_length=255)

    @field_validator("callback_url")
    @classmethod
    def callback_url_must_be_https_without_credentials(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("callback_url_must_be_public_https")
        return value


class WaLocationRequestOutcome(BaseModel):
    """Non-coordinate result returned by the Ordelo request endpoint."""

    request_id: UUID
    status: LocationRequestStatus
    source: LocationSource | None = None


class WhatsAppLocationReceipt(BaseModel):
    """Current-location response received from a rider's WhatsApp message."""

    rider_id: str = Field(min_length=1, max_length=50)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    observed_at: datetime
    inbound_message_id: str = Field(min_length=1, max_length=255)
    reply_to_message_id: str | None = Field(default=None, max_length=255)


class RestaurantConfirmationObservation(BaseModel):
    """Approximate restaurant point produced when pickup is confirmed."""

    order_number: str = Field(min_length=1, max_length=100)
    dispatch_id: int
    rider_id: str = Field(min_length=1, max_length=50)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    observed_at: datetime


class WaLocationCallbackPayload(BaseModel):
    """Open Ordelo-to-service location notification."""

    request_id: UUID
    order_number: str
    customer_id: str
    rider_id: str
    location_requested_by: LocationRequester
    requester_id: str
    location: dict[str, object]
