"""
Pydantic model for restaurant_master table
    . Defines fields and types to match the restaurant_master DDL
    . Handles nullability with Optional
    . Depends on pydantic, datetime, and config.client_ordelo
    . Models the restaurant_master table structure
    . Provides from_rest_ref to instantiate from DB
    . Provides get_admins to fetch admins column live from DB
  Functions/Classes:
    . RestaurantMaster
        . from_rest_ref
        . get_admins
"""

# %%
import datetime
from typing import Optional
from pydantic import BaseModel


class RestaurantMaster(BaseModel):
    rest_ref: str  # character varying, NOT NULL
    rest_id: Optional[str] = None  # character varying, NULL
    rest_name: str  # text, NOT NULL
    rest_email: Optional[str] = None  # text, NULL
    admins: Optional[list[str]] = None  # text[], NULL
    house_number: str  # text, NOT NULL
    building_name: Optional[str] = None  # text, NULL
    street_name: str  # text, NOT NULL
    city: str  # text, NOT NULL
    postcode: str  # text, NOT NULL
    lat: float  # double precision, NOT NULL
    lon: float  # double precision, NOT NULL
    dt: datetime.date  # date, NOT NULL
    dtts: datetime.datetime  # timestamp with time zone, NOT NULL

    @classmethod
    def from_rest_ref(cls, rest_ref: str):
        from config import client_ordelo

        resp = (
            client_ordelo.table("restaurant_master")
            .select("*")
            .eq("rest_ref", rest_ref.upper())
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
            raise ValueError(f"No restaurant found with rest_ref={rest_ref}")
        # Use the first row
        row = data[0]
        return cls(**row)

    def get_admins(self):
        """
        Fetches the current value of the 'admins' column from the DB for this restaurant.
        Returns a list of admin strings, or None if not set.
        """
        from config import client_ordelo

        resp = (
            client_ordelo.table("restaurant_master")
            .select("admins")
            .eq("rest_ref", self.rest_ref)
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
            raise ValueError(f"No restaurant found with rest_ref={self.rest_ref}")
        return data[0].get("admins")


# %%
RestaurantMaster.from_rest_ref("wren")
# from config import client_ordelo
# client_ordelo.table("restaurant_master").select("*").eq("rest_ref", "WREN").execute()
