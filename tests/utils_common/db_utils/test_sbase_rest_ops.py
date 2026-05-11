"""Tests for Supabase REST utility wrappers.

Covers filter-string generation plus representative async HTTP success and
failure branches through respx, without contacting Supabase.

Key Functions:
  - test_sql_to_supabase_rest_builds_supported_operators
  - test_get_sql_condition_new_builds_combined_condition
  - test_get_sql_condition_new_rejects_unsupported_values
  - test_sbase_call_function_posts_to_rpc_endpoint
  - test_sbase_get_returns_json_and_raises_supabase_error
  - test_sbase_insert_update_delete_success_paths
  - test_sbase_update_raises_value_error_on_error_response
"""

from __future__ import annotations

import httpx
import pytest
import respx

from utils_common.db_utils import sbase_rest_ops


BASE_URL = "https://test.supabase.co"


def test_sql_to_supabase_rest_builds_supported_operators() -> None:
    assert sbase_rest_ops.sql_to_supabase_rest(
        status="new",
        amount__gt=10,
        amount2__lt=20,
        name__like="%raj%",
        rider__neq="1",
    ) == "status=eq.new&amount=gt.10&amount2=lt.20&name=ilike.%raj%&rider=neq.1"


def test_get_sql_condition_new_builds_combined_condition() -> None:
    condition = sbase_rest_ops.get_sql_condition_new(
        status="new",
        amount=10,
        rider=["4474", "4488"],
        total=">=20",
        name="%raj%",
    )

    assert condition == "status = 'new' AND amount = 10 AND (rider = '4474' OR rider = '4488') AND total >= 20 AND name LIKE '%raj%'"


def test_get_sql_condition_new_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError, match="Invalid data type"):
        sbase_rest_ops.get_sql_condition_new(active=object())

    with pytest.raises(TypeError, match="Invalid data type in list"):
        sbase_rest_ops.get_sql_condition_new(status=[object()])


@respx.mock
async def test_sbase_call_function_posts_to_rpc_endpoint() -> None:
    route = respx.post(f"{BASE_URL}/rest/v1/rpc/test_func").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    result = await sbase_rest_ops.sbase_call_function("test_func", {"x": 1})

    assert result == {"ok": True}
    assert route.calls.last.request.content == b'{"x":1}'


@respx.mock
async def test_sbase_get_returns_json_and_raises_supabase_error() -> None:
    success = respx.get(f"{BASE_URL}/rest/v1/orders?status=eq.new").mock(
        return_value=httpx.Response(200, json=[{"id": 1}])
    )
    assert await sbase_rest_ops.sbase_get("orders", status="new") == [{"id": 1}]
    assert success.called

    respx.get(f"{BASE_URL}/rest/v1/orders?id=eq.1").mock(
        return_value=httpx.Response(200, json={"code": "PGRST", "message": "bad"})
    )
    with pytest.raises(ValueError, match="Supabase API Error"):
        await sbase_rest_ops.sbase_get("orders", id=1)


@respx.mock
async def test_sbase_insert_update_delete_success_paths() -> None:
    respx.post(f"{BASE_URL}/rest/v1/orders").mock(return_value=httpx.Response(201, text=""))
    respx.patch(f"{BASE_URL}/rest/v1/orders?id=eq.1").mock(return_value=httpx.Response(204, text=""))
    respx.delete(f"{BASE_URL}/rest/v1/orders").mock(return_value=httpx.Response(204, text=""))

    assert await sbase_rest_ops.sbase_insert("orders", {"id": 1}) is True
    assert await sbase_rest_ops.sbase_update({"status": "done"}, "orders", id=1) is True
    assert await sbase_rest_ops.sbase_delete("orders", id=1) is True


@respx.mock
async def test_sbase_update_raises_value_error_on_error_response() -> None:
    respx.patch(f"{BASE_URL}/rest/v1/orders?id=eq.1").mock(
        return_value=httpx.Response(400, json={"message": "bad update"})
    )

    with pytest.raises(ValueError, match="bad update"):
        await sbase_rest_ops.sbase_update({"status": "done"}, "orders", id=1)
