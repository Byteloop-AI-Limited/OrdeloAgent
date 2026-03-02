"""
Customer master data model for Pydantic validation.
  . Defines fields/types matching the customer_master DDL
  . Handles nullability with Optional fields and default coercions
  . Suitable for FastAPI and Langchain integration
Functions/Classes:
  . CustomerMaster
"""

# %%
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CustomerMaster(BaseModel):
    cust_id: str = Field(..., max_length=12)  # VARCHAR(12) PRIMARY KEY
    cust_name: str  # TEXT NOT NULL
    cust_email: Optional[str] = None  # TEXT NULL
    house_number: str  # TEXT NOT NULL
    building_name: Optional[str] = None  # TEXT NULL
    street_name: Optional[str] = None  # TEXT NULL
    city: str  # TEXT NOT NULL
    postcode: str  # TEXT NOT NULL
    lat: float  # FLOAT NOT NULL
    lon: float  # FLOAT NOT NULL
    consented_rest_refs: list[str] = []  # TEXT[] NOT NULL DEFAULT '{}'

    @classmethod
    def from_customer_id(cls, cust_id: str):
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
    def add_consented_rest_ref(cls, cust_id: str, rest_ref: str):
        from config import client_ordelo

        cust = cls.from_customer_id(cust_id)
        if rest_ref in cust.consented_rest_refs:
            return
        updated = cust.consented_rest_refs + [rest_ref]
        (
            client_ordelo.table("customer_master")
            .update({"consented_rest_refs": updated})
            .eq("cust_id", cust_id)
            .execute()
        )

    @field_validator("house_number", mode="before")
    def set_default_house_number(cls, v):
        """Set default house number to '999' if None is provided."""
        return v if v is not None else "999"

    @field_validator("street_name", mode="before")
    def default_empty_street(cls, v):
        """Coerce missing street_name to empty string."""
        return v if v is not None else ""


# %%
# _cust_master = CustomerMaster.from_customer_id("447448440754")
# 'ELAS' in _cust_master.consented_rest_refs
# await CustomerMaster.add_consented_rest_ref("447448440754", "CHKS")
