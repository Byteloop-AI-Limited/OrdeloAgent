"""Payment URL payload contract tests."""

from __future__ import annotations

import json

import httpx
import respx

from utils_common.payment_ms import payment


class _TakeawayOrder:
    payment_uri = "https://payment.example.com/payment-url"
    notes = "No onions"
    rest_ref = "ELAS"

    async def generate_product_order_summary(self) -> dict:
        return {
            "total": 12.5,
            "items": [
                {
                    "product_name": "Burger",
                    "quantity": 1,
                    "price": 12.5,
                    "modifications": [],
                }
            ],
        }


@respx.mock
async def test_generate_automatic_payment_url_uses_collection_auto_capture() -> None:
    route = respx.post(_TakeawayOrder.payment_uri).mock(
        return_value=httpx.Response(200, json={"url": "https://pay.example.com/auto"})
    )

    result = await payment.generate_automatic_payment_url(_TakeawayOrder())

    assert result == "https://pay.example.com/auto"
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["action"] == "collection"
    assert payload["manual_mode_capture"] is False
    assert payload["total_amount"] == 12.5


@respx.mock
async def test_generate_takeaway_manual_payment_url_uses_collection_manual_capture() -> None:
    route = respx.post(_TakeawayOrder.payment_uri).mock(
        return_value=httpx.Response(200, json={"url": "https://pay.example.com/manual"})
    )

    result = await payment.generate_takeaway_manual_payment_url(_TakeawayOrder())

    assert result == "https://pay.example.com/manual"
    payload = json.loads(route.calls[0].request.content)
    assert payload == {
        "total_amount": 12.5,
        "items": [
            {
                "product_name": "Burger",
                "quantity": 1,
                "price": 12.5,
                "modifications": [],
            }
        ],
        "currency": "GBP",
        "action": "collection",
        "restaurant_confirmation_code": "N/A",
        "manual_mode_capture": True,
        "notes": "No onions",
        "printonlyjob": False,
        "restRef": "ELAS",
    }
