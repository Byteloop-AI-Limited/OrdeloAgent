"""
Customer webhook handler module for OrdeloAgent.
  . Exposes REST endpoints for customer lifecycle operations
  . Creates or updates customers in customer_master
  . Updates customer delivery address and notifies restaurant
  . Upserts cust_rest_map consent records
  . Schedules restaurant-admin notifications for customer feedback submissions
  . Includes manual curl examples for endpoint checks
Functions/Classes:
  . CreateOrUpdateCustomerRequest - Pydantic request model for customer create-or-update
  . UpdateAddressRequest - Pydantic request model for address updates
  . UpdateCustRestMapRequest - Pydantic request model for consent map updates
  . RestaurantFeedbackRequest - Pydantic request model for customer feedback
  . create_or_update_customer - POST /create-or-update-customer
  . update_address - POST /update-address
  . update_cust_rest_map - POST /update-cust-rest-map
  . submit_restaurant_feedback - POST /restaurant-feedback
    . Routes customer notifications through the R1b notifier (always on since R3.1)

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . customer_master (table, ordelo_datamodels/core/customer_master.sql): named in code (passed to a query helper), updates
(end of database objects)
"""

from utils_common.notify import customer_notifier

# %%
import datetime
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from config import client_ordelo
from config.params import _resolve_rest_ref
from ordelo_datamodels.customer_master_pymodel import (
    CustomerMaster,
    CreateOrUpdateCustomerRequest,
    UpdateAddressRequest,
    UpdateCustRestMapRequest,
    RestaurantFeedbackRequest,
)
from ordelo_datamodels.cust_rest_map_pymodel import CustRestMap
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from loguru import logger
from utils_common.notify import restaurant_notifier
from utils_common.notify.restaurant_notifier import Feedback

# %%
router = APIRouter(tags=["customer-hooks"])


# %% Endpoints


@router.post(
    "/create-or-update-customer",
    summary="Create or update a customer in customer_master",
)
async def create_or_update_customer(request: CreateOrUpdateCustomerRequest):
    """
    Create or update a customer_master record.
    Omitted optional fields are excluded from the upsert payload and therefore
    do not overwrite existing database values.
    """
    try:
        CustomerMaster.from_cust_id(request.cust_id)
        existed = True
    except ValueError:
        existed = False

    payload = request.model_dump(exclude_unset=True)
    cust_master_update_payload = payload.copy()
    cust_master_update_payload["cust_id"] = request.cust_id

    if not existed:
        # For new customers, we need to set the city
        rest_ref = _resolve_rest_ref(request.rest_ref)
        city = RestaurantMaster.from_rest_ref(rest_ref).city
        payload["city"] = city
        # Also create a cust_rest_map record with has_consent=False
        _cust_master = CustomerMaster.upsert(**cust_master_update_payload)

        CustRestMap.upsert(
            cust_id=request.cust_id,
            rest_ref=rest_ref,
            has_consent=False,
        )

    else:
        # upsert customer_master
        _cust_master = CustomerMaster.upsert(**cust_master_update_payload)

    logger.info(
        f"Customer {'updated' if existed else 'created'} via upsert: {request.cust_id}"
    )

    return _cust_master


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
        raise HTTPException(
            status_code=404, detail=f"Customer {request.cust_id} not found"
        )

    logger.info(f"Address updated for customer {request.cust_id}")

    try:
        await customer_notifier.notify_address(request.rest_ref, request.cust_id, address_payload)
    except Exception as exc:
        logger.warning(f"Restaurant notification failed for {request.cust_id}: {exc}")

    return {"success": True, "cust_id": request.cust_id}


@router.post(
    "/update-cust-rest-map", summary="Upsert customer-restaurant consent mapping"
)
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
    logger.info(
        f"cust_rest_map upserted: cust_id={request.cust_id} rest_ref={request.rest_ref} has_consent={request.has_consent}"
    )
    return {"success": True, "record": record.model_dump()}


async def _notify_feedback_admins(
    *,
    admins: list[str],
    feedback_id: str,
    restaurant,
    request: RestaurantFeedbackRequest,
    received_at: datetime.datetime,
) -> None:
    await restaurant_notifier.notify(
        Feedback(
            admins=admins,
            feedback_id=feedback_id,
            restaurant_name=restaurant.rest_name,
            rest_ref=restaurant.rest_ref,
            cust_id=request.cust_id,
            cust_name=request.cust_name,
            order_reference=request.order_reference,
            description=request.description,
            received_at=received_at,
        )
    )


@router.post(
    "/restaurant-feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Schedule restaurant-admin notifications for customer feedback",
)
async def submit_restaurant_feedback(
    request: RestaurantFeedbackRequest,
    background_tasks: BackgroundTasks,
):
    """Validate feedback and return without waiting for WhatsApp delivery."""
    try:
        restaurant = RestaurantMaster.from_rest_ref(request.rest_ref)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Restaurant not found") from exc

    admins = list(
        dict.fromkeys(admin for admin in restaurant.get_admins() or [] if admin)
    )
    if not admins:
        raise HTTPException(status_code=503, detail="Restaurant administrators unavailable")

    feedback_id = f"FDB-{uuid.uuid4().hex[:12].upper()}"
    received_at = datetime.datetime.now(datetime.timezone.utc)
    background_tasks.add_task(
        _notify_feedback_admins,
        admins=admins,
        feedback_id=feedback_id,
        restaurant=restaurant,
        request=request,
        received_at=received_at,
    )
    logger.info(
        "Feedback notification scheduled feedback_id={} rest_ref={} admins={}",
        feedback_id,
        restaurant.rest_ref,
        len(admins),
    )
    return {
        "status": "accepted",
        "feedback_id": feedback_id,
        "rest_ref": restaurant.rest_ref,
        "admins_scheduled": len(admins),
    }


# %%
"""

curl -X POST http://localhost:3100/order-hooks/capture-address \
  -H "Content-Type: application/json" \
  -d '{
    "recipient": "447448440754",
    "rest_ref": "ELAS",
    "house_number": "221B",
    "building_name": null,
    "street_name": "Baker Street",
    "locality": null,
    "city": "London",
    "county": null,
    "postcode": "NW1 6XE",
    "country": "UK",
    "latitude": 51.523767,
    "longitude": -0.1585557
  }'

curl -X POST http://localhost:3100/customer-hooks/create-or-update-customer \
  -H "Content-Type: application/json" \
  -d '{
    "cust_id": "447448440754",
    "cust_name": "Lohith Holmes",
    "cust_email": "sherlock@example.com",
    "house_number":"ola",
    "building_name": null,
    "street_name": null,
    "city": null,
    "postcode": null,
    "lat": null,
    "lon": null
  }'


"""
