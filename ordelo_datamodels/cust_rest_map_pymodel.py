"""
Pydantic model for cust_rest_map table.
  . Tracks per-customer, per-restaurant consent
  . Composite primary key: (cust_id, rest_ref)
  . Provides from_cust_id_and_rest_ref to fetch a record
  . Provides upsert to insert or update a record
  . Provides ask_for_marketing_consent to determine whether consent should be requested again
Functions/Classes:
  . CustRestMap
      . from_cust_id_and_rest_ref
      . upsert
      . ask_for_marketing_consent
"""

# %%
import datetime
from typing import Optional
from pydantic import BaseModel


class CustRestMap(BaseModel):
    cust_id: str  # VARCHAR(12) NOT NULL, FK -> customer_master
    rest_ref: str  # VARCHAR(4) NOT NULL, FK -> restaurant_master
    has_consent: bool = False  # BOOLEAN NOT NULL DEFAULT FALSE
    consent_dtts: Optional[datetime.datetime] = None  # TIMESTAMP WITH TIME ZONE NULL
    dtts: Optional[datetime.datetime] = (
        None  # TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
    )

    @classmethod
    def from_cust_id_and_rest_ref(cls, cust_id: str, rest_ref: str) -> "CustRestMap":
        """Fetch the cust_rest_map record for the given customer and restaurant."""
        from config import client_ordelo

        resp = (
            client_ordelo.table("cust_rest_map")
            .select("*")
            .eq("cust_id", cust_id)
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
            raise ValueError(
                f"No cust_rest_map record found for cust_id={cust_id}, rest_ref={rest_ref}"
            )
        return cls(**data[0])

    @classmethod
    def upsert(
        cls,
        cust_id: str,
        rest_ref: str,
        has_consent: bool = False,
        consent_dtts: Optional[datetime.datetime] = None,
    ) -> "CustRestMap":
        """
        Insert or update a cust_rest_map record.
        dtts is set by DB DEFAULT on first insert and is never overwritten.
        consent_dtts is only included in the payload when provided.
        Returns the resulting CustRestMap instance.
        """
        from config import client_ordelo

        payload: dict = {
            "cust_id": cust_id,
            "rest_ref": rest_ref.upper(),
            "has_consent": has_consent,
            "consent_dtts": consent_dtts.isoformat() if consent_dtts else None,
        }

        resp = (
            client_ordelo.table("cust_rest_map")
            .upsert(payload, on_conflict="cust_id,rest_ref")
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
                f"Upsert failed for cust_id={cust_id}, rest_ref={rest_ref}"
            )
        return cls(**data[0])

    def ask_for_marketing_consent(self, number_of_days: int = 30) -> bool:
        """Return whether marketing consent should be requested again."""
        if number_of_days < 0:
            raise ValueError("number_of_days must be greater than or equal to 0")

        if self.has_consent:
            return False

        if self.consent_dtts is None:
            return True

        now = (
            datetime.datetime.now(self.consent_dtts.tzinfo)
            if self.consent_dtts.tzinfo
            else datetime.datetime.now()
        )
        return now - self.consent_dtts >= datetime.timedelta(days=number_of_days)


# %%
# ask_for_marketing_consent
# %%
