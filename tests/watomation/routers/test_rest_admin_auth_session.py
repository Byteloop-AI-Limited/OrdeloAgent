"""Restaurant-admin dashboard magic links (watomation/routers/rest_admin_auth_session.py).

Key Functions:
  - test_mint_for_restaurant_inserts_a_hashed_30_minute_session
  - test_mint_resolves_the_restaurant_then_delegates
  - test_mint_refuses_a_number_on_no_admin_list
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import pytest

from tests.fixtures.fake_supabase import FakeSupabaseResponse
from watomation.routers import rest_admin_auth_session as ras

APP = "https://restaurant-test.ordelo.app"


@pytest.fixture(autouse=True)
def app_url(monkeypatch):
    async def fake_url(role):
        assert role == "rest_admin"
        return APP

    monkeypatch.setattr(ras, "get_dashboard_app_url_async", fake_url)


async def test_mint_for_restaurant_inserts_a_hashed_30_minute_session(patch_supabase_client) -> None:
    url = await ras.mint_dashboard_session_for("447700900101", "elas")

    assert url.startswith(f"{APP}/rest-admin/activate/")
    token = url.rsplit("/", 1)[1]
    insert = [c for c in patch_supabase_client.calls if c.table == "auth_sessions" and c.verb == "insert"][-1]
    row = insert.payload
    assert row["role"] == "rest_admin" and row["scope_ref"] == "ELAS"
    assert row["principal_id"] == row["wa_number"] == "447700900101"
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in str(row)
    ttl = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
    assert ttl.total_seconds() == 30 * 60


async def test_mint_resolves_the_restaurant_then_delegates(patch_supabase_client) -> None:
    patch_supabase_client.register(
        table="restaurant_master", verb="select", response=FakeSupabaseResponse(data=[{"rest_ref": "WREN"}])
    )
    url = await ras.mint_dashboard_session("447700900101")
    lookup = [c for c in patch_supabase_client.calls if c.table == "restaurant_master"][-1]
    assert lookup.filters == {"cs:admins": ["447700900101"]}
    insert = [c for c in patch_supabase_client.calls if c.table == "auth_sessions" and c.verb == "insert"][-1]
    assert insert.payload["scope_ref"] == "WREN" and url.startswith(f"{APP}/rest-admin/activate/")


async def test_mint_refuses_a_number_on_no_admin_list(patch_supabase_client) -> None:
    patch_supabase_client.register(table="restaurant_master", verb="select", response=FakeSupabaseResponse(data=[]))
    with pytest.raises(ValueError):
        await ras.mint_dashboard_session("447700900199")
    assert not [c for c in patch_supabase_client.calls if c.table == "auth_sessions"]
