"""Tests for restaurant webhook/config lookup utilities.

These tests cover alias resolution, onboarding checks, cache reset behaviour,
webhook URL construction, overwatch parsing, and admin lookup using the shared
fake Supabase client.

Key Functions:
  - test_resolve_rest_ref_alias_and_passthrough
  - test_is_onboarded_rest_ref_resolves_alias
  - test_get_restaurant_base_url_async_caches_by_resolved_ref
  - test_reset_restaurant_base_url_cache_clears_all_or_one
  - test_get_restaurant_webhook_url_async_formats_known_path
  - test_get_restaurant_webhook_url_async_rejects_unknown_type
  - test_get_overwatch_list_parses_and_caches
  - test_reset_overwatch_list_cache
  - test_get_restaurant_admins_by_rest_ref_and_rest_id
  - test_get_restaurant_admins_requires_identifier
"""

from __future__ import annotations

import pytest

from config import params
from tests.fixtures.fake_supabase import FakeSupabaseResponse


@pytest.fixture(autouse=True)
def clear_param_caches():
    params.reset_restaurant_base_url_cache()
    params.reset_overwatch_list_cache()
    yield
    params.reset_restaurant_base_url_cache()
    params.reset_overwatch_list_cache()


def test_resolve_rest_ref_alias_and_passthrough() -> None:
    assert params._resolve_rest_ref("chks") == "ELAS"
    assert params._resolve_rest_ref("sfcs") == "SFCS"


def test_is_onboarded_rest_ref_resolves_alias() -> None:
    assert params.is_onboarded_rest_ref("chks") is True
    assert params.is_onboarded_rest_ref("elas") is True
    assert params.is_onboarded_rest_ref("unknown") is False


async def test_get_restaurant_base_url_async_caches_by_resolved_ref(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="ordelo_config",
        verb="select",
        response=FakeSupabaseResponse(data=[{"config_value": "https://elas.example.com"}]),
    )

    first = await params.get_restaurant_base_url_async("chks")
    second = await params.get_restaurant_base_url_async("ELAS")

    assert first == "https://elas.example.com"
    assert second == "https://elas.example.com"
    ordelo_config_selects = [c for c in patch_supabase_client.calls if c.table == "ordelo_config" and c.verb == "select"]
    assert len(ordelo_config_selects) == 1
    assert ordelo_config_selects[0].filters["eq:config_key"] == "ELAS_APP_URL"


def test_reset_restaurant_base_url_cache_clears_all_or_one() -> None:
    params._BASE_URL_CACHE["ELAS"] = ("https://elas.example.com", 999999999)
    params._BASE_URL_CACHE["SFCS"] = ("https://sfcs.example.com", 999999999)

    assert params.reset_restaurant_base_url_cache("elas") == 1
    assert "ELAS" not in params._BASE_URL_CACHE
    assert params.reset_restaurant_base_url_cache() == 1
    assert params._BASE_URL_CACHE == {}


async def test_get_restaurant_webhook_url_async_formats_known_path(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="ordelo_config",
        verb="select",
        response=FakeSupabaseResponse(data=[{"config_value": "https://elas.example.com"}]),
    )

    url = await params.get_restaurant_webhook_url_async("chks", "rider-inflight")

    assert url == "https://elas.example.com/rider-event-hooks/ELAS/rider-inflight"


async def test_get_restaurant_webhook_url_async_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown webhook type"):
        await params.get_restaurant_webhook_url_async("ELAS", "not-a-hook")


def test_get_overwatch_list_parses_and_caches(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="ordelo_config",
        verb="select",
        response=FakeSupabaseResponse(data=[{"config_value": " 111 ,222,, 333 "}]),
    )

    assert params.get_overwatch_list() == ["111", "222", "333"]
    assert params.get_overwatch_list() == ["111", "222", "333"]
    ordelo_config_selects = [c for c in patch_supabase_client.calls if c.table == "ordelo_config" and c.verb == "select"]
    assert len(ordelo_config_selects) == 1


def test_reset_overwatch_list_cache() -> None:
    params._OVERWATCH_LIST_CACHE = (["111"], 999999999)

    assert params.reset_overwatch_list_cache() == 1
    assert params.reset_overwatch_list_cache() == 0


def test_get_restaurant_admins_by_rest_ref_and_rest_id(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="restaurant_master",
        verb="select",
        response=FakeSupabaseResponse(data=[{"admins": ["111", "222"]}]),
    )

    assert params.get_restaurant_admins(rest_ref="chks") == ["111", "222"]
    assert patch_supabase_client.calls[-1].filters["eq:rest_ref"] == "ELAS"

    assert params.get_restaurant_admins(rest_id=123) == ["111", "222"]
    assert patch_supabase_client.calls[-1].filters["eq:rest_id"] == 123


def test_get_restaurant_admins_requires_identifier() -> None:
    with pytest.raises(ValueError, match="Either rest_ref or rest_id"):
        params.get_restaurant_admins()
