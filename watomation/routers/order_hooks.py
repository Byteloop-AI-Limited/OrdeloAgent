"""
Order hook endpoints for Elai Agent
  . Provides FastAPI router for order-related webhook operations
  . Supports retrieval of minimum order value configuration
  . Accepts restaurant coordinates directly or via rest_ref lookup
  . Delegates pricing lookup to watomation.services.order_service helpers
  . Creates new orders with order items and initiates payment capture
  . Returns payment URLs for customer checkout
Functions/Classes:
  . CreateOrderRequest - Pydantic model for order creation requests
  . get_min_order_value - Returns minimum order value using shared service helper
  . create_order - Creates order with items and captures payment
"""

# %%

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from config import logger
from utils_common.order_management.order_db_ops_new import OrderItem
from utils_common.order_management.order_service import (
    get_min_order_value as fetch_min_order_value,
    create_order_with_items,
)
from utils_common.payment_ms.payment import (
    generate_payment_intent,
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
        raise HTTPException(
            status_code=400,
            detail="rest_ref is required when restaurant coordinates are not provided",
        )

    try:
        # returns -1 if outside the range
        min_order_value = fetch_min_order_value(
            customer_latitude,
            customer_longitude,
            rest_lat=restaurant_latitude,
            rest_lon=restaurant_longitude,
            rest_ref=rest_ref,
        )
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

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
    # Create order with items
    order_result = await create_order_with_items(
        recipient=request.recipient,
        thread_id=request.thread_id,
        order_items=request.order_items,
        rest_ref=rest_ref,
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
    payment_intent_url = await generate_payment_intent(food_order)

    # Capture payment with static restaurant confirmation code
    # capture_payload = await food_order.gen_capture_payload()
    # restaurant_cc = 77
    # payment_url = await capture_payment_for_order(
    #     order_id=order_id,
    #     thread_id=thread_id,
    #     capture_payload=capture_payload,
    #     restaurant_cc=restaurant_cc,
    # )

    # if not payment_url:
    #     raise HTTPException(
    #         status_code=500,
    #         detail={
    #             "error": "Payment capture failed",
    #             "order_id": order_id,
    #             "order_number": order_number,
    #         },
    #     )

    return {
        "status": "success",
        "order_id": order_id,
        "recipient": request.recipient,
        "thread_id": request.thread_id,
        "order_number": order_number,
        "payment_intent_url": payment_intent_url,
    }
