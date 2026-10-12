"""Tests for new order database operations.

Uses lightweight dataclass stand-ins for pywa order/product payloads so the
production conversion logic and fake Supabase interactions are exercised.

Key Functions:
  - test_get_order_total_multiplies_price_by_quantity
  - test_create_order_reference_is_deterministic_and_uppercase
  - test_create_order_items_from_order_preserves_modifications
"""

from __future__ import annotations

from dataclasses import dataclass

from utils_common.order_management import order_db_ops_new
from tests.fixtures.fake_supabase import FakeSupabaseResponse


@dataclass
class _Product:
    sku: str
    quantity: int
    price: float
    product_name: str
    modifications: list[str] | None = None


@dataclass
class _Order:
    products: list[_Product]

    @property
    def total_price(self) -> float:
        return sum(product.price * product.quantity for product in self.products)


def _wa_order() -> _Order:
    return _Order(
        products=[
            _Product("burger", 2, 5.25, "Burger", ["No onions"]),
            _Product("chips", 1, 3.0, "Chips", None),
        ]
    )


def test_get_order_total_multiplies_price_by_quantity() -> None:
    assert order_db_ops_new.get_order_total(_wa_order()) == 13.5


def test_create_order_reference_is_deterministic_and_uppercase() -> None:
    first = order_db_ops_new.create_order_reference("447448440754", "2026-05-09")
    second = order_db_ops_new.create_order_reference("0754", "2026-05-09")

    assert first == second
    assert first.isupper()
    assert len(first) == 4


def test_create_order_items_from_order_preserves_modifications() -> None:
    items = order_db_ops_new.create_order_items_from_order

    async def _run():
        return await items(_wa_order(), "ABCD-1")

    import asyncio

    result = asyncio.run(_run())
    assert result[0].order_id == "ABCD-1"
    assert result[0].product_name == "Burger"
    assert result[0].modifications == ["No onions"]
