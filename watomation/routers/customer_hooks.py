"""
Customer webhook handler module for OrdeloAgent.
  . Exposes REST endpoints for customer lifecycle operations
  . Creates new customers in customer_master
  . Updates customer delivery address and notifies restaurant
  . Upserts cust_rest_map consent records
Functions/Classes:
  . CreateCustomerRequest - Pydantic request model for customer creation
  . UpdateAddressRequest - Pydantic request model for address updates
  . UpdateCustRestMapRequest - Pydantic request model for consent map updates
  . create_customer - POST /create-customer
  . update_address - POST /update-address
  . update_cust_rest_map - POST /update-cust-rest-map
"""

# %%
import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import client_ordelo
from config.params import get_restaurant_webhook_url_async
from ordelo_datamodels.customer_master_pymodel import CustomerMaster
from ordelo_datamodels.cust_rest_map_pymodel import CustRestMap
from loguru import logger

# %%
router = APIRouter(tags=["customer-hooks"])


# %% Request models

class CreateCustomerRequest(BaseModel):
    """Request model for creating a new customer."""

    cust_id: str
    cust_name: str
    cust_email: Optional[str] = None
    house_number: Optional[str] = None
    building_name: Optional[str] = None
    street_name: Optional[str] = None
    city: str
    postcode: str
    lat: float
    lon: float


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


class UpdateCustRestMapRequest(BaseModel):
    """Request model for upserting a cust_rest_map consent record."""

    cust_id: str
    rest_ref: str
    has_consent: bool
    consent_dtts: Optional[datetime.datetime] = None


# %% Endpoints

@router.post("/create-customer", summary="Create a new customer in customer_master")
async def create_customer(request: CreateCustomerRequest):
    """
    Insert a new customer record into customer_master.
    Raises 409 if the customer already exists.
    """
    existing = (
        client_ordelo.table("customer_master")
        .select("cust_id")
        .eq("cust_id", request.cust_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail=f"Customer {request.cust_id} already exists")

    customer = CustomerMaster(**request.model_dump())
    client_ordelo.table("customer_master").insert(customer.model_dump()).execute()
    logger.info(f"Customer created: {request.cust_id}")
    return {"success": True, "cust_id": request.cust_id}


@router.post("/update-address", summary="Update customer delivery address")
async def update_address(request: UpdateAddressRequest):
    """
    Update the address fields on an existing customer_master row and notify
    the restaurant via the order-address-update webhook.
    """
    address_payload = {
        "house_number": request.house_number,
        "building_name": request.building_name,
        "street_name": request.street_name,
        "city": request.city,
        "postcode": request.postcode,
        "lat": request.lat,
        "lon": request.lon,
    }

    response = (
        client_ordelo.table("customer_master")
        .update(address_payload)
        .eq("cust_id", request.cust_id)
        .execute()
    )
    if not response.data:
        raise HTTPException(status_code=404, detail=f"Customer {request.cust_id} not found")

    logger.info(f"Address updated for customer {request.cust_id}")

    try:
        webhook_url = await get_restaurant_webhook_url_async(request.rest_ref, "order-address-update")
        async with httpx.AsyncClient() as http_client:
            res = await http_client.post(
                url=f"{webhook_url}/{request.cust_id}",
                json=address_payload,
            )
            res.raise_for_status()
            logger.info(f"Restaurant {request.rest_ref} notified of address update for {request.cust_id}")
    except Exception as exc:
        logger.warning(f"Restaurant notification failed for {request.cust_id}: {exc}")

    return {"success": True, "cust_id": request.cust_id}


@router.post("/update-cust-rest-map", summary="Upsert customer-restaurant consent mapping")
async def update_cust_rest_map(request: UpdateCustRestMapRequest):
    """
    Insert or update a cust_rest_map record for the given customer and restaurant.
    dtts is preserved from the original insert; only has_consent and consent_dtts
    are updated on conflict.
    """
    record = CustRestMap.upsert(
        cust_id=request.cust_id,
        rest_ref=request.rest_ref,
        has_consent=request.has_consent,
        consent_dtts=request.consent_dtts,
    )
    logger.info(f"cust_rest_map upserted: cust_id={request.cust_id} rest_ref={request.rest_ref} has_consent={request.has_consent}")
    return {"success": True, "record": record.model_dump()}
