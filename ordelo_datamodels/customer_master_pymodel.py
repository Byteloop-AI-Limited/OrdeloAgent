"""
Customer master data model for validation, lookup, and upsert operations.
  . Defines fields/types matching the customer_master DDL
  . Handles nullability with Optional fields and default coercions
  . Fetches customer records by cust_id
  . Upserts customer rows using cust_id conflict handling
Functions/Classes:
  . CustomerMaster
      . from_cust_id
      . from_customer_id
      . upsert
  . RestaurantFeedbackRequest
"""

# %%
from typing import Optional
from pydantic import BaseModel, Field, field_validator
import datetime


class CustomerMaster(BaseModel):
    cust_id: str = Field(..., max_length=12)  # VARCHAR(12) PRIMARY KEY
    cust_name: Optional[str] = None  # TEXT NULL
    cust_email: Optional[str] = None  # TEXT NULL
    house_number: Optional[str] = None  # TEXT NUL
    building_name: Optional[str] = None  # TEXT NULL
    street_name: Optional[str] = None  # TEXT NULL
    city: Optional[str] = None  # TEXT NULL
    postcode: Optional[str] = None  # TEXT NULL
    lat: Optional[float] = None  # FLOAT NULL
    lon: Optional[float] = None  # FLOAT NULL

    @classmethod
    def from_cust_id(cls, cust_id: str) -> "CustomerMaster":
        from config import client_ordelo

        resp = (
            client_ordelo.table("customer_master")
            .select("*")
            .eq("cust_id", cust_id)
            .execute()
        )
        data = (
            resp["data"]
            if isinstance(resp, dict) and "data" in resp
            else resp.data
            if hasattr(resp, "data")
            else None
        )
        if not data or len(data) == 0:
            raise ValueError(f"No customer found with cust_id={cust_id}")
        row = data[0]
        return cls(**row)

    @classmethod
    def from_customer_id(cls, cust_id: str) -> "CustomerMaster":
        return cls.from_cust_id(cust_id)

    @classmethod
    def upsert(cls, **payload) -> "CustomerMaster":
        from config import client_ordelo

        filtered_payload = {
            key: value for key, value in payload.items() if key in cls.model_fields
        }
        if not filtered_payload.get("cust_id"):
            raise ValueError("cust_id is required for customer upsert")

        validated_payload = cls.model_validate(filtered_payload).model_dump(
            exclude_unset=True
        )

        resp = (
            client_ordelo.table("customer_master")
            .upsert(validated_payload, on_conflict="cust_id")
            .execute()
        )
        data = (
            resp["data"]
            if isinstance(resp, dict) and "data" in resp
            else resp.data
            if hasattr(resp, "data")
            else None
        )
        if not data or len(data) == 0:
            raise ValueError(
                f"Upsert failed for customer with cust_id={validated_payload['cust_id']}"
            )
        return cls(**data[0])

    # @classmethod
    # def add_consented_rest_ref(cls, cust_id: str, rest_ref: str):
    #     from config import client_ordelo

    #     cust = cls.from_customer_id(cust_id)
    #     if rest_ref in cust.consented_rest_refs:
    #         return
    #     updated = cust.consented_rest_refs + [rest_ref]
    #     (
    #         client_ordelo.table("customer_master")
    #         .update({"consented_rest_refs": updated})
    #         .eq("cust_id", cust_id)
    #         .execute()
    #     )

    @field_validator("house_number", mode="before")
    def set_default_house_number(cls, v):
        """Set default house number to '999' if None is provided."""
        return v if v is not None else "999"

    @field_validator("street_name", mode="before")
    def default_empty_street(cls, v):
        """Coerce missing street_name to empty string."""
        return v if v is not None else ""


# %%
class CreateOrUpdateCustomerRequest(BaseModel):
    """Request model for creating or updating a customer."""

    cust_id: str
    rest_ref: str
    cust_name: Optional[str] = None
    cust_email: Optional[str] = None
    house_number: Optional[str] = None
    building_name: Optional[str] = None
    street_name: Optional[str] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


# %%


class UpdateAddressRequest(BaseModel):
    """Request model for updating a customer's delivery address."""

    cust_id: str
    rest_ref: str
    house_number: Optional[str] = None
    building_name: Optional[str] = None
    street_name: Optional[str] = None
    city: str
    postcode: str
    lat: float
    lon: float


# %%


class UpdateCustRestMapRequest(BaseModel):
    """Request model for upserting a cust_rest_map consent record."""

    cust_id: str
    rest_ref: str
    has_consent: bool
    consent_dtts: Optional[datetime.datetime] = None


class RestaurantFeedbackRequest(BaseModel):
    """Validated, ephemeral customer feedback submitted to Ordelo."""

    rest_ref: str = Field(..., min_length=1, max_length=32)
    cust_id: str = Field(..., min_length=3, max_length=32)
    cust_name: Optional[str] = Field(default=None, max_length=160)
    order_reference: Optional[str] = Field(default=None, max_length=80)
    description: str = Field(..., min_length=5, max_length=2000)


# %%
# _cust_master = CustomerMaster.from_customer_id("4474484407541")
# _cust_master
# 'ELAS' in _cust_master.consented_rest_refs
# await CustomerMaster.add_consented_rest_ref("447448440754", "CHKS")
