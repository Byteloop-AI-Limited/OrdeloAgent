"""create_food_order_with_items refusals (order_intake_block) reach the WhatsApp order path as typed errors."""

from types import SimpleNamespace

import pytest

from utils_common.order_management import order_service
from utils_common.order_management.order_service import order_refusal


@pytest.mark.parametrize("msg, code", [
    ("{'code': 'P0C01', 'message': 'order_refused: closed_date'}", "restaurant_closed"),
    ("order_refused: hidden_items DETAIL ...", "items_unavailable"),
    ("{'code': 'P0C02'}", "items_unavailable"),
    ("duplicate key value violates unique constraint", None),
])
def test_order_refusal(msg, code):
    assert order_refusal(msg) == code


async def test_insert_maps_the_refusal(monkeypatch):
    class Client:
        def rpc(self, name, args):
            def boom():
                raise RuntimeError("{'code': 'P0C02', 'message': 'order_refused: hidden_items'}")
            return SimpleNamespace(execute=boom)

    monkeypatch.setattr(order_service, "client_ordelo", Client())
    out = await order_service._insert_order_rpc({"order_id": "X"}, [])
    assert out == {"success": False, "error": "items_unavailable",
                   "details": order_service.REFUSAL_MESSAGES["items_unavailable"], "duplicate_order_id": False}
