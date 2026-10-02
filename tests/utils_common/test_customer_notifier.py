"""Channel isolation, no-retry delivery, recovery and pilot configuration."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from config.feature_flags import reset_feature_flag_cache
from utils_common.notify import customer_notifier as n


def row(**changes):
    return {
        "order_number": "BNAT-ABCD-1",
        "data": {
            "webhook_type": "rider-cust-cc",
            "path_suffix": "/BNAT-ABCD-1/447400000000",
            "payload": {},
        },
        "channel": "whatsapp_restaurant",
        "active": True,
        "origin_channel": "whatsapp",
        "recipient": "447400000000",
        "destination": "447400000000",
        "detail_level": "full",
    } | changes


@pytest.mark.parametrize(
    "changes",
    [
        {"origin_channel": "web"},
        {"recipient": "W7K2M9QX4TPA"},
        {"channel": "web_page"},
        {"active": False},
        {"detail_level": "status_only"},
        {"destination": "someone_else"},
        {"channel": "whatsapp_agg"},
    ],
)
@respx.mock
async def test_incompatible_channels_never_send(monkeypatch, changes):
    monkeypatch.setattr(n, "_claim", AsyncMock(return_value=row(**changes)))
    finish = AsyncMock()
    monkeypatch.setattr(n, "_finish", finish)
    await n.dispatch(1)
    assert len(respx.calls) == 0
    assert finish.await_args.args[1] == "skipped"


@pytest.mark.parametrize(
    "response", [httpx.Response(500), httpx.ReadTimeout("ambiguous")]
)
@respx.mock
async def test_failed_restaurant_request_is_attempted_once(monkeypatch, response):
    claimed = False

    async def claim(outbox_id):
        nonlocal claimed
        if claimed:
            return None
        claimed = True
        return row()

    monkeypatch.setattr(n, "_claim", claim)
    monkeypatch.setattr(
        n,
        "get_restaurant_webhook_url_async",
        AsyncMock(return_value="https://restaurant.example/delivered"),
    )
    finish = AsyncMock()
    monkeypatch.setattr(n, "_finish", finish)
    route = respx.post("https://restaurant.example/delivered/BNAT-ABCD-1/447400000000")
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    await asyncio.gather(n.dispatch(1), n.dispatch(1))
    await n.dispatch(1)
    assert route.call_count == 1
    finish.assert_awaited_once()
    assert finish.await_args.args[1] == "failed"


async def test_missing_flag_off_and_bnat_allowlist(monkeypatch, feature_flags):
    monkeypatch.setattr(n, "config_csv", AsyncMock(return_value=frozenset({"BNAT"})))
    assert not await n.enabled_for("BNAT")
    feature_flags.add("CUSTOMER_NOTIFIER_ENABLED")
    reset_feature_flag_cache()
    assert await n.enabled_for("bnat")
    assert not await n.enabled_for("ELAS")
    monkeypatch.setattr(n, "config_csv", AsyncMock(return_value=frozenset()))
    assert await n.enabled_for("ELAS")


async def test_rollout_lookup_failure_does_not_enable_all_restaurants(
    monkeypatch, feature_flags
):
    feature_flags.add("CUSTOMER_NOTIFIER_ENABLED")
    monkeypatch.setattr(
        n, "config_csv", AsyncMock(side_effect=RuntimeError("database down"))
    )
    assert not await n.enabled_for("ELAS")


@respx.mock
async def test_web_address_is_skipped(monkeypatch):
    await n.notify_address("BNAT", "W7K2M9QX4TPA", {"postcode": "BR6 6DN"})
    assert len(respx.calls) == 0


async def test_persistence_failure_does_not_send_legacy_fallback(monkeypatch, patch_supabase_client):
    monkeypatch.setattr(
        n, "_record", AsyncMock(side_effect=RuntimeError("database down"))
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(n, "dispatch", dispatch)
    await n.publish(
        "BNAT-ABCD-1", n.CustomerOrderEvent("delivered", "delivered", "rider-cust-cc")
    )
    dispatch.assert_not_awaited()
    assert any(call.table == 'order_customer_event' and call.verb == 'upsert' for call in patch_supabase_client.calls)


async def test_sweep_only_recovers_pending_unattempted_rows(
    monkeypatch, patch_pg_pool, feature_flags
):
    feature_flags.add("CUSTOMER_NOTIFIER_ENABLED")
    patch_pg_pool.register_sql(
        "SELECT o.id,e.order_number", [{"id": 1, "order_number": "BNAT-ABCD-1"}]
    )
    monkeypatch.setattr(n, "config_csv", AsyncMock(return_value=frozenset({"BNAT"})))
    dispatch = AsyncMock()
    monkeypatch.setattr(n, "dispatch", dispatch)
    assert await n.sweep_pending() == 1
    dispatch.assert_awaited_once_with(1)
    assert "attempts=0" in patch_pg_pool.all_executes[-1].sql


async def test_origin_subscriptions_and_event_outbox_share_transaction(
    monkeypatch, patch_pg_pool
):
    patch_pg_pool.register_sql(
        "SELECT order_number, recipient, origin_channel",
        [
            {
                "order_number": "BNAT-ABCD-1",
                "recipient": "W7K2M9QX4TPA",
                "origin_channel": "web",
            }
        ],
    )
    patch_pg_pool.register_sql("SELECT id FROM order_customer_event", [{"id": 7}])
    patch_pg_pool.register_sql("SELECT id FROM notification_outbox", [{"id": 9}])
    event = n.CustomerOrderEvent(
        "payment_authorised", "payment_authorised", "order-payment-complete"
    )
    assert await n._record("BNAT-ABCD-1", event) == [9]
    queries = patch_pg_pool.all_executes
    assert any("pg_advisory_xact_lock" in q.sql for q in queries)
    subscription = next(
        q for q in queries if "INSERT INTO order_notification_subscription" in q.sql
    )
    assert subscription.params == ("BNAT-ABCD-1", "web_page", None)
    assert any(
        "ON CONFLICT (order_number,event_key) DO NOTHING" in q.sql for q in queries
    )
    assert any(
        "ON CONFLICT(event_id,subscription_id) DO NOTHING" in q.sql for q in queries
    )
