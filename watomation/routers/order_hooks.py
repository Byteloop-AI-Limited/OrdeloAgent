"""
Order hook endpoints for Elai Agent
  . Provides FastAPI router for order-related webhook operations
  . Supports retrieval of minimum order value configuration
  . Accepts restaurant coordinates directly, via postcode resolution, or rest_ref lookup
  . Delegates pricing lookup to watomation.services.order_service helpers
  . Creates new orders with order items and initiates payment capture
  . Returns payment URLs for customer checkout
  . Captures customer addresses and upserts into customer_master
Functions/Classes:
  . CreateOrderRequest - Pydantic model for order creation requests
  . CaptureAddressRequest - Pydantic model for address capture requests
  . get_min_order_value - Returns minimum order value using shared service helper
  . get_min_order_value_by_postcode - Resolves postcodes to coordinates before lookup
  . create_order - Creates order with items and captures payment
  . capture_address - Captures customer address and upserts into customer_master
"""

# %%

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from config import logger, client_ordelo, get_restaurant_webhook_url_async
import httpx
from ordelo_datamodels.customer_master_pymodel import CustomerMaster
from utils_common.order_management.order_db_ops_new import OrderItem
from utils_common.order_management.order_service import (
    get_min_order_value as fetch_min_order_value,
    create_order_with_items,
)
from utils_common.maps_service.address_resolver import address_resolver
from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster
from utils_common.payment_ms.payment import (
    generate_payment_intent_url,
    generate_automatic_payment_url,
    cancel_payment,
)

from utils_common.order_management.food_order_pymodel import FoodOrder

router = APIRouter(tags=["order-hooks"])


# %%
@router.get(
    "/get-min-order-value",
    summary="Retrieve minimum order value for current tenant",
    description="""
    Calculates minimum order value for the provided order context using shared service utilities.

    `customer_latitude` and `customer_longitude` must be provided. Restaurant coordinates can
    be supplied directly or resolved via `rest_ref`.
    """,
)
async def get_min_order_value(
    customer_latitude: float = Query(..., description="Customer latitude"),
    customer_longitude: float = Query(..., description="Customer longitude"),
    restaurant_latitude: Optional[float] = Query(
        default=None,
        description="Restaurant latitude when coordinates supplied directly",
    ),
    restaurant_longitude: Optional[float] = Query(
        default=None,
        description="Restaurant longitude when coordinates supplied directly",
    ),
    rest_ref: Optional[str] = Query(
        default=None,
        description="Restaurant reference used to resolve coordinates when latitude/longitude are absent",
    ),
):
    has_rest_coords = (
        restaurant_latitude is not None or restaurant_longitude is not None
    )
    if has_rest_coords and (
        restaurant_latitude is None or restaurant_longitude is None
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "restaurant_latitude and restaurant_longitude must both be provided "
                "when specifying explicit restaurant coordinates"
            ),
        )

    if not has_rest_coords and not rest_ref:
        logger.info("rest_ref is required when restaurant coordinates are not provided")
        raise HTTPException(
            status_code=400,
            detail="rest_ref is required when restaurant coordinates are not provided",
        )

    if not has_rest_coords and rest_ref:
        try:
            rest_master = RestaurantMaster.from_rest_ref(rest_ref)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        restaurant_latitude = rest_master.lat
        restaurant_longitude = rest_master.lon

    try:
        # returns -1 if outside the range
        min_order_value = fetch_min_order_value(
            customer_latitude,
            customer_longitude,
            rest_lat=restaurant_latitude,
            rest_lon=restaurant_longitude,
            rest_ref=rest_ref,
        )
        logger.info(f"Minimum order value for {rest_ref}: {min_order_value}")
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return {
        "status": "ok",
        "min_order_value": min_order_value,
        "source": "service" if min_order_value is not None else "pricing-service",
    }


@router.get(
    "/get-min-order-value-by-postcode",
    summary="Retrieve minimum order value using postcode/coordinate inputs",
    description="""
    Resolves customer postcodes into coordinates and accepts either a restaurant
    postcode lookup or rest_ref override before calculating minimum order value.

    Provide restaurant_postcode when rest_ref is unavailable.
    """,
)
async def get_min_order_value_by_postcode(
    customer_postcode: str = Query(..., description="Customer UK postcode"),
    restaurant_postcode: Optional[str] = Query(
        default=None,
        description="Restaurant UK postcode used when rest_ref is absent",
    ),
    rest_ref: Optional[str] = Query(
        default=None,
        description="Restaurant reference used to resolve coordinates when postcode is absent",
    ),
):
    customer_address = address_resolver.get_address_from_postcode(customer_postcode)
    if not customer_address.latitude or not customer_address.longitude:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to resolve customer_postcode {customer_postcode}",
        )

    if not rest_ref and not restaurant_postcode:
        raise HTTPException(
            status_code=400,
            detail=(
                "restaurant_postcode or rest_ref is required to resolve restaurant location"
            ),
        )

    restaurant_lat: Optional[float] = None
    restaurant_lon: Optional[float] = None

    if rest_ref:
        try:
            rest_master = RestaurantMaster.from_rest_ref(rest_ref)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=str(err)) from err
        restaurant_lat = rest_master.lat
        restaurant_lon = rest_master.lon
    elif restaurant_postcode:
        restaurant_address = address_resolver.get_address_from_postcode(
            restaurant_postcode
        )
        if not restaurant_address.latitude or not restaurant_address.longitude:
            raise HTTPException(
                status_code=400,
                detail=f"Unable to resolve restaurant_postcode {restaurant_postcode}",
            )
        restaurant_lat = restaurant_address.latitude
        restaurant_lon = restaurant_address.longitude

    try:
        min_order_value = fetch_min_order_value(
            customer_address.latitude,
            customer_address.longitude,
            rest_lat=restaurant_lat,
            rest_lon=restaurant_lon,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return {
        "status": "ok",
        "min_order_value": min_order_value,
        "source": "service" if min_order_value is not None else "pricing-service",
    }


class CreateOrderRequest(BaseModel):
    """Request model for creating a new order."""

    recipient: str
    thread_id: str
    order_items: List[OrderItem]
    order_type: str
    notes: Optional[str] = None


@router.post(
    "/create-order/{rest_ref}",
    summary="Create a new order with payment capture",
    description="""
    Creates a new food order with the provided order items and initiates payment capture.
    Returns the payment URL for the customer to complete the payment.
    {
    "recipient": "447448440754",
    "thread_id": "1239876lkjsd",
    "order_items": [
        {
        "order_id": "elas-123",
        "product_name": "Chicken Burger",
        "sku": "chicken_burger",
        "quantity": 1,
        "price": 20
        }
    ]
    }
    """,
)
async def create_order(
    rest_ref: str,
    request: CreateOrderRequest,
):
    """
    Creates a new order and captures payment.

    Args:
        rest_ref: Restaurant reference code
        request: Order creation request with recipient, thread_id, and order_items

    Returns:
        Dict with order details and payment URL
    """

    # Temp logic; Also check if notes is not None
    _notes = request.notes.lower() if request.notes else ""

    action = request.order_type

    # Create order with items
    order_result = await create_order_with_items(
        recipient=request.recipient,
        thread_id=request.thread_id,
        order_items=request.order_items,
        rest_ref=rest_ref,
        action=action,
        notes=request.notes,
    )

    # update final order values (below calls the update)
    food_order = FoodOrder.from_order_id(order_id=order_result["order_id"])
    if not food_order:
        logger.error(f"FoodOrder not found for order_id: {order_result['order_id']}")
        return None

    # Check if order creation was successful
    if not order_result.get("success"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": order_result.get("error"),
                "details": order_result.get("details"),
            },
        )

    order_id = order_result["order_id"]
    order_number = order_result["order_number"]

    thread_id = food_order.thread_id

    if food_order.action == "delivery":
        payment_intent_url = await generate_payment_intent_url(food_order)
    else:
        payment_intent_url = await generate_automatic_payment_url(food_order)

    return {
        "status": "success",
        "order_id": order_id,
        "recipient": request.recipient,
        "thread_id": request.thread_id,
        "order_number": order_number,
        "payment_intent_url": payment_intent_url,
        "service_charge": food_order.service_charge,
        "delivery_fee": food_order.delivery_fee,
        "small_order_fee": food_order.small_order_fee,
        "notes": food_order.notes,
    }


# %%
@router.get("/postcode-validator/{postcode}")
async def validate_postcode(postcode: str):
    """Validate UK postcode using address resolver.

    Args:
        request: The FastAPI request object

    Returns:
        HTML response indicating validation status
    """
    # Get form data and extract postcode
    uk_address = address_resolver.get_address_from_postcode(postcode)

    return uk_address


# %%
class CaptureAddressRequest(BaseModel):
    """Request model for capturing customer address."""

    recipient: str
    rest_ref: str
    house_number: Optional[str] = None
    building_name: Optional[str] = None
    street_name: Optional[str] = None
    locality: Optional[str] = None
    city: str
    county: Optional[str] = None
    postcode: str
    country: Optional[str] = None
    latitude: float
    longitude: float


@router.post("/capture-address")
async def capture_address(request: CaptureAddressRequest):
    """Capture customer address and upsert into customer_master.

    Args:
        request: CaptureAddressRequest containing address details

    Returns:
        dict with success status and customer data
    """
    customer_master_pl = {
        "cust_id": request.recipient,
        "cust_name": request.recipient,  # Using recipient as name since not provided
        "house_number": request.house_number,
        "building_name": request.building_name,
        "street_name": request.street_name,
        "city": request.city,
        "postcode": request.postcode,
        "lat": request.latitude,
        "lon": request.longitude,
    }
    rest_ref = request.rest_ref
    logger.info(f"restRef is :{rest_ref}")
    _customer_master_row = CustomerMaster(**customer_master_pl)

    response = (
        client_ordelo.table("customer_master")
        .upsert(_customer_master_row.model_dump())
        .execute()
    )

    logger.info(f"Customer address captured for {request.recipient}")

    webhook_url = await get_restaurant_webhook_url_async(
        rest_ref, "order-address-update"
    )
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=f"{webhook_url}/{request.recipient}",
            json=_customer_master_row.model_dump(),
        )
        logger.info("Restaurant notified of rider")
        logger.info("Status code:", response.status_code)

    return {"success": True}
