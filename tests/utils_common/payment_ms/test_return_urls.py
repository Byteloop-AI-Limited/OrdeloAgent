"""Stripe return URL builders."""

from __future__ import annotations

import pytest

from utils_common.payment_ms.return_urls import (
    order_link,
    storefront_base,
    wa_chat_url,
    wa_return_urls,
    web_return_urls,
)


async def test_web_return_urls_built_from_storefront_url(config_values) -> None:
    config_values["RESTAURANT_MENU_APP_URL"] = "https://restaurant-test.ordelo.app/"

    assert await web_return_urls("ELAS-ABCD-1") == {
        "success_url": "https://restaurant-test.ordelo.app/checkout/return?order=ELAS-ABCD-1",
        "cancel_url": "https://restaurant-test.ordelo.app/checkout?resume=1",
    }


async def test_web_return_urls_success_is_secret_order_link_when_token_given(config_values) -> None:
    config_values["RESTAURANT_MENU_APP_URL"] = "https://restaurant-test.ordelo.app"
    token = "a" * 43

    assert await web_return_urls("ELAS-ABCD-1", token) == {
        "success_url": f"https://restaurant-test.ordelo.app/o/{token}",
        "cancel_url": "https://restaurant-test.ordelo.app/checkout?resume=1",
    }


async def test_web_return_urls_none_when_storefront_url_unset(config_values) -> None:
    assert await web_return_urls("ELAS-ABCD-1") is None


@pytest.mark.parametrize(
    ("rest_ref", "link"),
    [
        ("elas", "https://wa.me/message/AIDICBLAE4KZH1"),
        ("SFCS", "https://wa.me/message/KLHBN7UOKO7UE1"),
        ("bnat", "https://wa.me/message/F7QYDTUOIVCNI1"),
    ],
)
def test_wa_return_urls_maps_known_restaurants(rest_ref: str, link: str) -> None:
    assert wa_return_urls(rest_ref) == {"success_url": link, "cancel_url": link}


@pytest.mark.parametrize("rest_ref", ["crms", "", None])
def test_wa_return_urls_none_for_unknown_restaurant(rest_ref) -> None:
    assert wa_return_urls(rest_ref) is None


async def test_storefront_base_strips_trailing_slash(config_values) -> None:
    config_values["RESTAURANT_MENU_APP_URL"] = "https://restaurant.ordelo.app/"
    assert await storefront_base() == "https://restaurant.ordelo.app"


async def test_storefront_base_none_when_unset(config_values) -> None:
    assert await storefront_base() is None


def test_order_link_quotes_token() -> None:
    assert order_link("https://x.app", "ab_-Z") == "https://x.app/o/ab_-Z"


@pytest.mark.parametrize(
    ("rest_ref", "link"),
    [("elas", "https://wa.me/message/AIDICBLAE4KZH1"), ("CRMS", None), ("", None), (None, None)],
)
def test_wa_chat_url(rest_ref, link) -> None:
    assert wa_chat_url(rest_ref) == link
