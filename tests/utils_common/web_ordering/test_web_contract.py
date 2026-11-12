"""R3 negative-path, access, payment-state and WhatsApp coexistence contracts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.fixtures.fake_supabase import FakeSupabaseResponse
from utils_common.web_ordering import (
    availability,
    order_access,
    customer_order_view,
    web_checkout,
    lifecycle,
)
from utils_common.web_ordering import common
from utils_common.web_ordering.common import RESTAURANTS, WebError
from watomation.routers import web_hooks, takeaway_hooks
from ordelo.agents import rider_agent
from tests.ordelo.agents.test_rider_agent import _runtime
from tests.watomation.routers.test_takeaway_hooks import _takeaway_summary_row

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
FOOD = {"action": "delivery", "payment_status": "requires_payment", "order_dtts": NOW}
KEY = "a" * 43


def test_registry_towns_and_phones():
    for entry in RESTAURANTS.values():
        assert entry["town"]
        assert entry["phone"]
    assert RESTAURANTS["CRMS"] == {"town": "orpington", "phone": "01689838792"}
    assert RESTAURANTS["BNAT"] == {"town": "orpington", "phone": "01689637476"}
    assert RESTAURANTS["CRDO"] == {"town": "orpington", "phone": "01689332664"}


@pytest.mark.parametrize("rest_refs", [("BNAT", "CRMS"), ("CRMS", "BNAT")])
async def test_orpington_delivery_eligibility(monkeypatch, rest_refs):
    monkeypatch.setattr(
        availability, "geocode", AsyncMock(return_value={"lat": 51.37, "lng": 0.10})
    )
    monkeypatch.setattr(
        availability,
        "available",
        AsyncMock(side_effect=lambda ref, mode: {"rest_ref": ref}),
    )
    monkeypatch.setattr(
        availability,
        "pricing",
        AsyncMock(return_value={"minimum_order_value": 10, "delivery_fee": 2.5}),
    )

    result = await availability.eligibility("BR6 0TW", "delivery", rest_refs)

    assert result["town_slug"] == "orpington"
    assert [row["rest_ref"] for row in result["restaurants"]] == list(rest_refs)
    assert all(row["status"] == "deliverable" for row in result["restaurants"])


@pytest.mark.parametrize("minutes,expected", [(0, True), (59, True), (60, False)])
def test_new_order_cutoff(minutes, expected):
    at = datetime(
        2026, 10, 2, 21, minutes if minutes < 60 else 0, tzinfo=availability.UK
    )
    if minutes == 60:
        at += timedelta(hours=1)
    # Closes 22:15, order cutoff is 22:00.
    assert availability.opening({"fri": [["21:00", "22:15"]]}, at, 15)[0] is expected


def test_overnight_cutoff_and_weekend_next_open():
    hours = {"fri": [["23:00", "25:00"]]}
    assert availability.opening(
        hours, datetime(2026, 10, 3, 0, 44, tzinfo=availability.UK), 15
    )[0]
    assert not availability.opening(
        hours, datetime(2026, 10, 3, 0, 45, tzinfo=availability.UK), 15
    )[0]
    assert availability.opening(
        hours, datetime(2026, 10, 3, 3, tzinfo=availability.UK), 15
    )[1].startswith("2026-10-09T23:00")


@pytest.mark.parametrize("token", ["", "short", "a" * 42, "a" * 44, "!" * 43])
def test_malformed_access_rejected(token):
    with pytest.raises(WebError) as caught:
        order_access.digest(token)
    assert caught.value.status == 401


async def test_order_token_cannot_open_another_order(monkeypatch):
    monkeypatch.setattr(
        order_access,
        "one",
        AsyncMock(return_value={"order_number": "ELAS-A-1", "detail_level": "full"}),
    )
    with pytest.raises(WebError) as caught:
        await order_access.verify(KEY, "ELAS-B-2")
    assert caught.value.status == 403


async def test_expired_or_unknown_token_rejected(monkeypatch):
    monkeypatch.setattr(order_access, "one", AsyncMock(return_value=None))
    with pytest.raises(WebError) as caught:
        await order_access.verify(KEY, "ELAS-A-1")
    assert caught.value.status == 401


@pytest.mark.parametrize(
    "value",
    [
        {"quantity": 0},
        {"quantity": 1.5},
        {"price": -1},
        {"price": "NaN"},
        {"price": "Infinity"},
        {"price": "1.001"},
    ],
)
def test_invalid_order_item_never_accepted(value):
    with pytest.raises(ValidationError):
        web_checkout.Item(
            **({"sku": "s", "product_name": "Item", "price": 1, "quantity": 1} | value)
        )


def test_all_accepted_lines_retained_and_limit_enforced():
    body = {
        "thread_id": "WEB-1",
        "cust_id": "WTEST",
        "rest_ref": "ELAS",
        "order_items": [
            {"sku": str(i), "product_name": "Item", "price": 1, "quantity": 1}
            for i in range(20)
        ],
    }
    assert len(web_checkout.OrderInput(**body).order_items) == 20
    body["order_items"].append(body["order_items"][0])
    with pytest.raises(ValidationError):
        web_checkout.OrderInput(**body)


@pytest.mark.parametrize(
    "events,state",
    [
        ([], "authorised"),
        ([{"event_type": "payment_captured", "data": {}}], "captured"),
        (
            [
                {
                    "event_type": "no_rider_found",
                    "data": {"payload": {"payment_cancelled": False}},
                }
            ],
            "release_pending",
        ),
        (
            [
                {
                    "event_type": "no_rider_found",
                    "data": {"payload": {"payment_cancelled": True}},
                }
            ],
            "released",
        ),
    ],
)
def test_payment_display_does_not_trust_stale_order_column(events, state):
    food = FOOD | {"payment_status": "requires_capture"}
    assert customer_order_view.derive(food, {}, {}, events, at=NOW)[1] == state


def test_waiting_payment_window_is_35_minutes():
    assert (
        customer_order_view.derive(FOOD, {}, {}, [], at=NOW + timedelta(minutes=34))[0]
        == "confirming_payment"
    )
    assert (
        customer_order_view.derive(FOOD, {}, {}, [], at=NOW + timedelta(minutes=36))[0]
        == "payment_not_completed"
    )


async def test_web_rider_contact_never_sends_invalid_card(
    patch_supabase_client, fake_async_wa
):
    patch_supabase_client.register(
        table="delivery_summary",
        verb="select",
        response=FakeSupabaseResponse(data=[{"customer_id": "W7K2M9QX4TPA"}]),
    )
    result = await rider_agent.send_customer_contact(
        {"order_number": "ELAS-ABCD-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )
    assert [s.method for s in fake_async_wa.sent] == ["send_message"]
    assert "No customer phone number" in fake_async_wa.sent[0].kwargs["text"]
    assert result.update["messages"][-1].content.startswith("/dontRespond")


async def test_whatsapp_rider_contact_still_sends_card(
    patch_supabase_client, fake_async_wa
):
    patch_supabase_client.register(
        table="delivery_summary",
        verb="select",
        response=FakeSupabaseResponse(data=[{"customer_id": "447400000000"}]),
    )
    await rider_agent.send_customer_contact(
        {"order_number": "ELAS-ABCD-1"},
        "tool-1",
        _runtime(client=patch_supabase_client, wa=fake_async_wa),
    )
    assert [s.method for s in fake_async_wa.sent] == ["send_contact"]


async def test_web_takeaway_decline_does_not_whatsapp_customer(
    monkeypatch, patch_supabase_client, fake_async_wa
):
    monkeypatch.setattr(takeaway_hooks, "_async_wa_client", fake_async_wa)
    monkeypatch.setattr(takeaway_hooks, "cancel_payment", AsyncMock(return_value=None))
    publish = AsyncMock()
    monkeypatch.setattr(takeaway_hooks.customer_notifier, "publish", publish)
    release = AsyncMock()
    monkeypatch.setattr(lifecycle, "query", release)
    summary = takeaway_hooks.TakeawaySummaryData(
        **_takeaway_summary_row(customer_id="W7K2M9QX4TPA")
    )
    food = takeaway_hooks.FoodOrder(
        order_id="ABCD-1",
        order_number="ELAS-ABCD-1",
        recipient=summary.customer_id,
        thread_id="WEB-1",
        action="takeaway",
        total_price=10,
        payment_status="requires_capture",
    )
    await takeaway_hooks._handle_restaurant_decline(summary, food)
    assert not fake_async_wa.sent
    assert publish.await_args.args[1].payload["payment_cancelled"] is False
    # The unconfirmed cancellation is queued for recovery (always on since R3.1).
    assert release.await_args.args[1] == ("ELAS-ABCD-1", "restaurant_declined")


async def test_unknown_restaurant_never_contacts_payments():
    with pytest.raises(WebError):
        await availability.restaurant("WREN")


ALWAYS_OPEN = {day: [["00:00", "48:00"]] for day in availability.DAYS}


async def test_registry_restaurant_is_open_with_no_config_rows(monkeypatch, feature_flags):
    """R3.1 (D35): no allowlist or rollout rows; being in the registry is enough."""
    row = {"rest_ref": "ELAS", "service_hours_json": ALWAYS_OPEN}
    monkeypatch.setattr(availability, "restaurant", AsyncMock(return_value=row))

    assert await availability.available("ELAS", "delivery") == row
    assert await availability.available("ELAS", "collection") == row


async def test_emergency_pause_stops_new_web_orders(monkeypatch, feature_flags):
    row = {"rest_ref": "ELAS", "service_hours_json": ALWAYS_OPEN}
    monkeypatch.setattr(availability, "restaurant", AsyncMock(return_value=row))
    feature_flags.add("ELAS_WEB_ORDERING_PAUSED")

    with pytest.raises(WebError) as caught:
        await availability.available("ELAS", "collection")
    assert (caught.value.status, caught.value.body["error"]) == (503, "ordering_paused")
    # Tracking an existing order is never paused.
    assert await availability.available("ELAS", "collection", new_order=False) == row


async def test_status_only_view_redacts_before_return(monkeypatch):
    async def one(sql, params=()):
        if "FROM food_order" in sql:
            return FOOD | {
                "order_number": "ELAS-ABCD-1",
                "order_id": "ABCD-1",
                "total_price": 10,
                "origin_channel": "web",
            }
        if "FROM restaurant_master" in sql:
            return {"rest_name": "Elai"}
        if "FROM delivery_summary" in sql:
            return {"customer_address": "private", "cust_confirmation_code": 22}
        return None

    monkeypatch.setattr(customer_order_view, "one", one)
    monkeypatch.setattr(customer_order_view, "query", AsyncMock(return_value=[]))
    view = await customer_order_view.get_view("ELAS-ABCD-1", "status_only")
    assert not {"delivery", "items", "charges", "notes"} & view.keys()


async def test_release_recovery_does_not_repeat_confirmed_cancellation(monkeypatch):
    from watomation.routers import delivery_hooks

    monkeypatch.setattr(lifecycle, "one", AsyncMock(return_value={"exists": 1}))
    persist = AsyncMock()
    cancel = AsyncMock()
    monkeypatch.setattr(lifecycle, "query", persist)
    monkeypatch.setattr(delivery_hooks, "cancel_payment", cancel)
    await lifecycle.release("ELAS-ABCD-1")
    cancel.assert_not_awaited()
    assert "completed_at=now()" in persist.await_args.args[0]


async def test_failed_web_cancellation_queues_durable_recovery(monkeypatch, feature_flags):
    """R3.1: no WEB_LATE_PAYMENT_GUARD_ENABLED row; recovery is always queued."""
    persist = AsyncMock()
    monkeypatch.setattr(lifecycle, "query", persist)
    await lifecycle.queue_release("ELAS-ABCD-1", "no_rider_found")
    assert persist.await_args.args[1] == ("ELAS-ABCD-1", "no_rider_found")
    assert "ON CONFLICT DO NOTHING" in persist.await_args.args[0]


def test_new_web_routes_require_server_secret(monkeypatch):
    monkeypatch.setenv("ORDELO_WEB_KEY", "x" * 48)
    app = FastAPI()
    app.include_router(web_hooks.router, prefix="/web")

    @app.exception_handler(WebError)
    async def errors(request, exc):
        return web_hooks.JSONResponse(exc.body, exc.status)

    client = TestClient(app)
    assert client.get("/web/orders/ELAS-ABCD-1").status_code == 401
    assert (
        client.post(
            "/web/access/exchange", headers={"X-Ordelo-Web-Key": "wrong"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/web/access/whatsapp-link",
            json={"order_number": "ELAS-ABCD-1", "recipient": "447700900123"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "body,error",
    [
        (
            {
                "delivery_options": [
                    {"vehicle_type": "car", "minimum_order_value": None}
                ]
            },
            "pricing_unavailable",
        ),
        (
            {"delivery_options": [{"vehicle_type": "car", "minimum_order_value": "2"}]},
            "pricing_unavailable",
        ),
        (
            {
                "delivery_options": [
                    {"vehicle_type": "car", "minimum_order_value": float("nan")}
                ]
            },
            "pricing_unavailable",
        ),
        (
            {"delivery_options": [{"vehicle_type": "car", "minimum_order_value": -1}]},
            "out_of_range",
        ),
        ({"delivery_options": []}, "out_of_range"),
        ({"delivery_options": "bad"}, "pricing_unavailable"),
    ],
)
async def test_pricing_failure_distinguished_from_range(monkeypatch, body, error):
    monkeypatch.setattr(availability, "_call_pricing_service", lambda payload: body)
    with pytest.raises(WebError) as caught:
        await availability.pricing(
            {"rest_ref": "ELAS", "lat": 51, "lon": 0}, {"lat": 51, "lng": 0}
        )
    assert caught.value.body["error"] == error


async def test_estimate_fee_uses_pricing_breakdown(monkeypatch):
    monkeypatch.setattr(
        availability,
        "_call_pricing_service",
        lambda payload: {
            "delivery_options": [
                {
                    "vehicle_type": "car",
                    "minimum_order_value": 15,
                    "breakdown": {"delivery_fee": 1.49},
                }
            ]
        },
    )
    assert (
        await availability.pricing(
            {"rest_ref": "ELAS", "lat": 51, "lon": 0}, {"lat": 51, "lng": 0}
        )
    )["delivery_fee"] == 1.49


def test_confirmed_release_survives_missing_event():
    status, state, _, _ = customer_order_view.derive(
        FOOD, {}, {}, [], release={"completed_at": NOW}, at=NOW
    )
    assert (status, state) == ("cancelled", "released")


async def test_late_guard_never_interferes_with_whatsapp(monkeypatch, feature_flags):
    monkeypatch.setattr(
        lifecycle, "one", AsyncMock(return_value=FOOD | {"origin_channel": "whatsapp"})
    )
    assert await lifecycle.reject_late(SimpleNamespace(order_id="1")) is None


async def test_late_web_authorisation_is_durably_rejected(monkeypatch, patch_pg_pool, feature_flags):
    """R3.1: no WEB_LATE_PAYMENT_GUARD_ENABLED row needed."""
    monkeypatch.setattr(lifecycle, "utcnow", lambda: NOW + timedelta(minutes=36))
    monkeypatch.setattr(
        lifecycle,
        "one",
        AsyncMock(
            side_effect=[
                FOOD
                | {
                    "origin_channel": "web",
                    "order_number": "ELAS-A-1",
                    "thread_id": "WEB-1",
                },
                None,
            ]
        ),
    )
    patch_pg_pool.register_sql(
        "SELECT payment_status", [{"payment_status": "requires_payment"}]
    )
    patch_pg_pool.register_sql("INSERT INTO payment_event", [{"id": 1}])
    event = SimpleNamespace(
        order_id="A-1",
        provider_event_id="evt_1",
        payment_intent_id="pi_1",
        amount_pence=1000,
    )
    assert await lifecycle.reject_late(event) == "late_rejected"
    sql = " ".join(rec.sql for rec in patch_pg_pool.all_executes)
    assert "INSERT INTO web_payment_release" in sql
    assert "UPDATE thread SET is_active=false" in sql
    assert "init_delivery" not in sql and "requires_capture" not in sql


@pytest.mark.parametrize(
    "price,menu,discount,expected",
    [
        (10, 10, 0, False),
        (9.99, 10, 0, False),
        (9, 10, 0, True),
        (8, 10, 20, False),
        (7.90, 10, 20, True),
    ],
)
def test_price_floor_allows_rounding_and_configured_discount(
    price, menu, discount, expected
):
    from utils_common.web_ordering.monitoring import below_floor

    assert below_floor(price, menu, discount) is expected


async def test_price_audit_runs_without_a_switch(monkeypatch, feature_flags):
    """R3.1: no WEB_PRICE_MONITOR_ENABLED row; the daily audit claims its run."""
    from utils_common.web_ordering import monitoring

    claim = AsyncMock(return_value=[])  # another worker already claimed today
    monkeypatch.setattr(monitoring, "query", claim)
    await monitoring.sweep()
    assert "INSERT INTO web_monitor_run" in claim.await_args.args[0]


def _google_reply(monkeypatch, postcode, **extra):
    """Stub the Google geocode call; no network or API key involved."""
    import sys

    monkeypatch.setitem(
        sys.modules,
        "utils_common.maps_service.address_resolver",
        SimpleNamespace(API_KEY="test"),
    )
    result = {
        "geometry": {"location": {"lat": 51.07, "lng": -1.79}},
        "address_components": [{"long_name": postcode, "types": ["postal_code"]}],
        **extra,
    }
    reply = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"status": "OK", "results": [result]},
    )
    monkeypatch.setattr(availability.requests, "get", lambda *a, **k: reply)


@pytest.mark.parametrize(
    "typed, found",
    [("SP1 3TA", "SP1 3UE"), ("SP13TA", "SP1 3TA"), ("sp1 3ta", "SP1 3TA")],
)
async def test_geocode_accepts_postcode_within_same_sector(monkeypatch, typed, found):
    _google_reply(monkeypatch, found)
    location = await availability.geocode("1 Mill Stream Approach", expected_postcode=typed)
    assert location == {"lat": 51.07, "lng": -1.79}


@pytest.mark.parametrize("found", ["SP2 8AB", "BR6 6DN", ""])
async def test_geocode_rejects_postcode_outside_sector(monkeypatch, found):
    _google_reply(monkeypatch, found)
    with pytest.raises(WebError) as error:
        await availability.geocode("1 Mill Stream Approach", expected_postcode="SP1 3TA")
    assert error.value.body["error"] == "invalid_address"


ADDRESS = {"house_number": "1", "street": "Mill Stream Approach", "town": "Salisbury"}
CENTROID = {"lat": 51.0657, "lng": -1.7885}
PIN = {"lat": 51.0650, "lng": -1.7890}
LOCATED = {"centroid": CENTROID, "pin": PIN, "precision": "street"}


def _address_session(monkeypatch, mode="delivery", postcode="SP1 2AB"):
    meta = {"mode": mode, "postcode_district": "SP1", "postcode": postcode}
    monkeypatch.setattr(web_checkout, "session", AsyncMock(return_value=meta))
    locate = AsyncMock(return_value=LOCATED)
    monkeypatch.setattr(availability, "locate", locate)
    monkeypatch.setattr(web_checkout, "query", AsyncMock())
    return locate


def _saved_postcode():
    return web_checkout.query.await_args.args[1][0].obj["postcode"]


@pytest.mark.parametrize("sent", ["SP1 2AB", "sp12ab", "SP1 2ZZ", None])
async def test_address_uses_stored_postcode_inside_sector(monkeypatch, sent):
    _address_session(monkeypatch)
    value = {**ADDRESS, **({"postcode": sent} if sent else {})}
    assert await web_checkout.address("t", "W1", value) == {"ok": True}
    assert _saved_postcode() == "SP1 2AB"  # the server's postcode, not the request's


@pytest.mark.parametrize("sent", ["SP1 3TA", "SP2 8AB", "SP10 1AA", "BR6 0TW"])
async def test_address_rejects_postcode_outside_checkout_sector(monkeypatch, sent):
    locate = _address_session(monkeypatch)
    with pytest.raises(WebError) as error:
        await web_checkout.address("t", "W1", {**ADDRESS, "postcode": sent})
    assert error.value.body["error"] == "postcode_mismatch"
    locate.assert_not_awaited()


@pytest.mark.parametrize("stored", [None, ""])
async def test_address_fails_closed_without_stored_postcode(monkeypatch, stored):
    locate = _address_session(monkeypatch, postcode=stored)
    with pytest.raises(WebError) as error:
        await web_checkout.address("t", "W1", {**ADDRESS, "postcode": "SP1 2AB"})
    assert (error.value.status, error.value.body["error"]) == (409, "checkout_restart_required")
    locate.assert_not_awaited()


@pytest.mark.parametrize("mode, sent", [("delivery", "nonsense"), ("delivery", "SP1"), ("collection", None), ("collection", "x")])
async def test_address_rejects_malformed_postcode(monkeypatch, mode, sent):
    locate = _address_session(monkeypatch, mode=mode)
    value = {**ADDRESS, **({"postcode": sent} if sent else {})}
    with pytest.raises(WebError) as error:
        await web_checkout.address("t", "W1", value)
    assert error.value.body["error"] == "invalid_address"
    locate.assert_not_awaited()


async def test_collection_address_needs_no_stored_postcode(monkeypatch):
    _address_session(monkeypatch, mode="collection", postcode=None)
    assert await web_checkout.address("t", "W1", {**ADDRESS, "postcode": "BR6 0TW"}) == {"ok": True}


# ADR 0008: the address never blocks checkout. The locked postcode's centroid
# prices the minimum; Google's result is only the rider pin when it stays in
# the postcode sector, otherwise the pin falls back to the centroid.


def _google_replies(monkeypatch, replies):
    """Stub Google per address text: replies maps a substring to (status, result)."""
    import sys

    monkeypatch.setitem(
        sys.modules,
        "utils_common.maps_service.address_resolver",
        SimpleNamespace(API_KEY="test"),
    )

    calls = []

    def get(url, params, timeout):
        calls.append(params["address"])
        status, result = next(v for k, v in replies.items() if k in params["address"])
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"status": status, "results": [result] if result else []},
        )

    monkeypatch.setattr(availability.requests, "get", get)
    return calls


def _result(lat, postcode, types, partial=None):
    result = {
        "geometry": {"location": {"lat": lat, "lng": -1.79}},
        "address_components": [{"long_name": postcode, "types": ["postal_code"]}],
        "types": types,
    }
    if partial:
        result["partial_match"] = True
    return result


POSTCODE_REPLY = ("OK", _result(51.0657, "SP1 2AB", ["postal_code"]))


@pytest.mark.parametrize(
    "types, partial, precision",
    [
        (["street_address"], None, "exact"),
        (["premise"], None, "exact"),
        (["route"], True, "street"),  # "Rose Cottage, Churchill Way East"
        (["route"], None, "street"),
    ],
)
async def test_locate_uses_google_pin_inside_sector(monkeypatch, types, partial, precision):
    _google_replies(
        monkeypatch,
        {"Churchill": ("OK", _result(51.0650, "SP1 2AB", types, partial)), "SP1 2AB": POSTCODE_REPLY},
    )
    located = await availability.locate("Rose Cottage, Churchill Way East, Salisbury, SP1 2AB", "SP1 2AB")
    assert located == {
        "centroid": {"lat": 51.0657, "lng": -1.79},
        "pin": {"lat": 51.0650, "lng": -1.79},
        "precision": precision,
    }


@pytest.mark.parametrize(
    "reply",
    [
        ("OK", _result(51.07, "SP1 1HZ", ["street_address"])),  # other sector
        ("OK", _result(51.07, "SP2 8AB", ["route"], True)),  # other district
        ("OK", _result(51.07, "", ["locality"], True)),  # town only
        ("OK", _result(51.07, "SP1 2AB", ["postal_code"], True)),  # postcode only
        ("ZERO_RESULTS", None),
        ("OVER_QUERY_LIMIT", None),
    ],
)
async def test_locate_falls_back_to_postcode_centroid(monkeypatch, reply):
    _google_replies(monkeypatch, {"Churchill": reply, "SP1 2AB": POSTCODE_REPLY})
    located = await availability.locate("1 Churchill Way E, Salisbury, SP1 2AB", "SP1 2AB")
    assert located["pin"] == located["centroid"] == {"lat": 51.0657, "lng": -1.79}
    assert located["precision"] == "postcode"


async def test_locate_needs_the_locked_postcode_to_price(monkeypatch):
    _google_replies(monkeypatch, {"Churchill": POSTCODE_REPLY, "SP1 2AB": ("ZERO_RESULTS", None)})
    with pytest.raises(WebError) as error:
        await availability.locate("Churchill Way E, Salisbury, SP1 2AB", "SP1 2AB")
    assert error.value.body["error"] == "invalid_address"


@pytest.mark.parametrize(
    "premises",
    [{}, {"building": "Rose Cottage"}, {"house_number": "1"}, {"flat": "2"}],
)
async def test_address_saves_without_house_number_and_keeps_pin_and_centroid(monkeypatch, premises):
    _address_session(monkeypatch)
    value = {"street": "Churchill Way East", "town": "Salisbury", "postcode": "SP1 2AB", **premises}
    assert await web_checkout.address("t", "W1", value) == {"ok": True}
    snapshot = web_checkout.query.await_args.args[1][0].obj
    assert snapshot["street"] == "Churchill Way East"  # the customer's text wins
    assert (snapshot["latitude"], snapshot["longitude"]) == (PIN["lat"], PIN["lng"])
    assert (snapshot["postcode_latitude"], snapshot["postcode_longitude"]) == (CENTROID["lat"], CENTROID["lng"])
    assert snapshot["pin_precision"] == "street"
    availability.locate.assert_awaited_once_with(
        web_checkout.address_display(value | {"postcode": "SP1 2AB"}),
        "SP1 2AB",
        street_address="Churchill Way East, Salisbury, SP1 2AB",
    )


@pytest.mark.parametrize("missing", ["street", "town"])
async def test_address_still_needs_street_and_town(monkeypatch, missing):
    locate = _address_session(monkeypatch)
    value = {**ADDRESS, "postcode": "SP1 2AB", missing: " "}
    with pytest.raises(WebError) as error:
        await web_checkout.address("t", "W1", value)
    assert error.value.body["error"] == "invalid_address"
    locate.assert_not_awaited()


def test_minimum_is_priced_from_postcode_centroid():
    addr = {"latitude": 1.0, "longitude": 2.0, "postcode_latitude": 3.0, "postcode_longitude": 4.0}
    assert web_checkout.pricing_location(addr) == {"lat": 3.0, "lng": 4.0}
    # Snapshots saved before ADR 0008 have only the geocoded address point.
    assert web_checkout.pricing_location({"latitude": 1.0, "longitude": 2.0}) == {"lat": 1.0, "lng": 2.0}


@pytest.mark.parametrize(
    "precision, note",
    [
        ("exact", None),
        (None, None),
        ("street", "Address not verified: map pin is on the street, not the door. Use the address text."),
        ("postcode", "Address not verified: map pin is the postcode centre. Use the address text."),
    ],
)
def test_rider_is_told_when_the_pin_is_approximate(precision, note):
    assert web_checkout.pin_note({"pin_precision": precision}) == note


FULL = "1, Churchill Way East, Salisbury, SP1 2AB"
STREET = "Churchill Way East, Salisbury, SP1 2AB"
OTHER_SECTOR = ("OK", _result(51.07, "SP1 1HZ", ["street_address"]))  # Google's interpolated door guess


async def test_locate_retries_street_only_when_door_lands_outside_sector(monkeypatch):
    calls = _google_replies(
        monkeypatch,
        {"1, Churchill": OTHER_SECTOR, "Churchill": ("OK", _result(51.0650, "SP1 2AB", ["route"])), "SP1 2AB": POSTCODE_REPLY},
    )
    located = await availability.locate(FULL, "SP1 2AB", street_address=STREET)
    assert located["precision"] == "street"
    assert located["pin"] == {"lat": 51.0650, "lng": -1.79}
    assert calls == ["SP1 2AB", FULL, STREET]


async def test_locate_retry_is_never_better_than_street(monkeypatch):
    _google_replies(
        monkeypatch,
        {"1, Churchill": OTHER_SECTOR, "Churchill": ("OK", _result(51.0650, "SP1 2AB", ["street_address"])), "SP1 2AB": POSTCODE_REPLY},
    )
    located = await availability.locate(FULL, "SP1 2AB", street_address=STREET)
    assert located["precision"] == "street"


async def test_locate_retries_when_full_address_not_found(monkeypatch):
    _google_replies(
        monkeypatch,
        {"1, Churchill": ("ZERO_RESULTS", None), "Churchill": ("OK", _result(51.0650, "SP1 2AB", ["route"])), "SP1 2AB": POSTCODE_REPLY},
    )
    assert (await availability.locate(FULL, "SP1 2AB", street_address=STREET))["precision"] == "street"


async def test_locate_uses_centroid_when_retry_is_outside_sector_too(monkeypatch):
    _google_replies(
        monkeypatch,
        {"1, Churchill": OTHER_SECTOR, "Churchill": ("OK", _result(51.07, "SP1 1HZ", ["route"])), "SP1 2AB": POSTCODE_REPLY},
    )
    located = await availability.locate(FULL, "SP1 2AB", street_address=STREET)
    assert located["precision"] == "postcode"
    assert located["pin"] == located["centroid"]


async def test_locate_skips_retry_without_premises(monkeypatch):
    calls = _google_replies(monkeypatch, {"Churchill": OTHER_SECTOR, "SP1 2AB": POSTCODE_REPLY})
    located = await availability.locate(STREET, "SP1 2AB", street_address=STREET)
    assert located["precision"] == "postcode"
    assert calls == ["SP1 2AB", STREET]


async def test_locate_skips_retry_on_provider_error(monkeypatch):
    calls = _google_replies(
        monkeypatch,
        {"Churchill": ("OVER_QUERY_LIMIT", None), "SP1 2AB": POSTCODE_REPLY},
    )
    located = await availability.locate(FULL, "SP1 2AB", street_address=STREET)
    assert located["precision"] == "postcode"
    assert calls == ["SP1 2AB", FULL]


@pytest.mark.parametrize(
    "value, expected",
    [("SP1 2AB", "SP1 2AB"), ("sp12ab", "SP1 2AB"), (" sp1  2ab ", "SP1 2AB"), ("BR6 0TW", "BR6 0TW"),
     ("W1A 1AA", "W1A 1AA"), ("SP1", None), ("", None), (None, None), ("12345", None)],
)
def test_normalise_postcode(value, expected):
    assert common.normalise_postcode(value) == expected


@pytest.mark.parametrize(
    "value, sector",
    [("SP1 2AB", "SP12"), ("sp12zz", "SP12"), ("SP10 1AA", "SP101"), ("SP1", ""), (None, "")],
)
def test_postcode_sector(value, sector):
    assert common.postcode_sector(value) == sector


def _start_session(monkeypatch):
    monkeypatch.setattr(availability, "available", AsyncMock())
    monkeypatch.setattr(web_checkout, "one", AsyncMock(return_value={"thread_id": "T1"}))
    monkeypatch.setattr(web_checkout, "query", AsyncMock())


async def test_start_stores_normalised_postcode(monkeypatch):
    _start_session(monkeypatch)
    await web_checkout.start("ELAS", "delivery", "salisbury", "v1", "SP1", postcode="sp12ab")
    params = web_checkout.query.await_args.args[1]
    assert "SP1 2AB" in params and "SP1" in params


async def test_start_rejects_postcode_outside_its_district(monkeypatch):
    _start_session(monkeypatch)
    with pytest.raises(WebError) as error:
        await web_checkout.start("ELAS", "delivery", "salisbury", "v1", "SP1", postcode="SP2 8AB")
    assert error.value.body["error"] == "postcode_mismatch"
    web_checkout.query.assert_not_awaited()


@pytest.mark.parametrize("mode, postcode", [("delivery", None), ("delivery", "nonsense"), ("collection", "SP1 2AB")])
async def test_start_stores_null_without_a_usable_delivery_postcode(monkeypatch, mode, postcode):
    _start_session(monkeypatch)
    await web_checkout.start("ELAS", mode, "salisbury", "v1", "SP1", postcode=postcode)
    assert "SP1 2AB" not in web_checkout.query.await_args.args[1]
    assert None in web_checkout.query.await_args.args[1]


# --- WhatsApp order page: link minting and view ---------------------------------

WA_ORDER = {
    "origin_channel": "whatsapp",
    "recipient": "447700900123",
    "payment_status": "authorised",
}


def _wa_one(monkeypatch, row):
    monkeypatch.setattr(order_access, "one", AsyncMock(return_value=row))


async def test_issue_for_whatsapp_inserts_grant_and_returns_token(monkeypatch):
    _wa_one(monkeypatch, WA_ORDER)
    expires = NOW + timedelta(days=30)
    run = AsyncMock(return_value=[{"id": 1, "expires_at": expires}])
    monkeypatch.setattr(order_access, "query", run)
    token, got = await order_access.issue_for_whatsapp("ELAS-ABCD-1", "447700900123")
    assert len(token) == 43 and got == expires
    sql = run.await_args.args[0]
    assert "origin_channel='whatsapp'" in sql and "recipient=%s" in sql
    assert "payment_status<>'requires_payment'" in sql
    assert token not in str(run.await_args.args[1])  # only the hash is stored


@pytest.mark.parametrize(
    "order_number,row,recipient,status,error",
    [
        ("ELAS-ABCD-1", None, "447700900123", 404, "not_found"),
        ("ZZZZ-ABCD-1", WA_ORDER, "447700900123", 404, "not_found"),
        ("ELAS-ABCD-1", WA_ORDER | {"origin_channel": "web"}, "447700900123", 409, "web_order"),
        ("ELAS-ABCD-1", WA_ORDER | {"payment_status": "requires_payment"}, "447700900123", 409, "not_paid"),
        ("ELAS-ABCD-1", WA_ORDER, "447700900999", 403, "forbidden"),
    ],
)
async def test_issue_for_whatsapp_refusals_never_insert(
    monkeypatch, order_number, row, recipient, status, error
):
    _wa_one(monkeypatch, row)
    run = AsyncMock(return_value=[])
    monkeypatch.setattr(order_access, "query", run)
    with pytest.raises(WebError) as caught:
        await order_access.issue_for_whatsapp(order_number, recipient)
    assert (caught.value.status, caught.value.body["error"]) == (status, error)
    run.assert_not_awaited()


def _link_client(monkeypatch):
    monkeypatch.setenv("ORDELO_WEB_KEY", "x" * 48)
    app = FastAPI()
    app.include_router(web_hooks.router, prefix="/web")

    @app.exception_handler(WebError)
    async def errors(request, exc):
        return web_hooks.JSONResponse(exc.body, exc.status)

    return TestClient(app)


LINK_REQ = {"order_number": "ELAS-ABCD-1", "recipient": "447700900123"}
LINK_HEADERS = {"X-Ordelo-Web-Key": "x" * 48}


def test_whatsapp_link_503_without_storefront_url_and_no_grant(monkeypatch):
    mint = AsyncMock()
    monkeypatch.setattr(web_hooks.order_access, "issue_for_whatsapp", mint)
    monkeypatch.setattr(web_hooks, "storefront_base", AsyncMock(return_value=None))
    r = _link_client(monkeypatch).post("/web/access/whatsapp-link", json=LINK_REQ, headers=LINK_HEADERS)
    assert r.status_code == 503 and r.json()["error"] == "link_unavailable"
    mint.assert_not_awaited()


def test_whatsapp_link_returns_private_url(monkeypatch):
    token = "a" * 43
    monkeypatch.setattr(
        web_hooks.order_access,
        "issue_for_whatsapp",
        AsyncMock(return_value=(token, NOW + timedelta(days=30))),
    )
    monkeypatch.setattr(
        web_hooks, "storefront_base", AsyncMock(return_value="https://restaurant.ordelo.app")
    )
    r = _link_client(monkeypatch).post("/web/access/whatsapp-link", json=LINK_REQ, headers=LINK_HEADERS)
    assert r.status_code == 201
    assert r.json()["url"] == f"https://restaurant.ordelo.app/o/{token}"
    assert r.headers["cache-control"] == "private, no-store"


def test_whatsapp_link_rejects_bad_order_number(monkeypatch):
    r = _link_client(monkeypatch).post(
        "/web/access/whatsapp-link",
        json=LINK_REQ | {"order_number": "bad"},
        headers=LINK_HEADERS,
    )
    assert r.status_code == 422


def _view_one(origin, action="delivery"):
    async def one(sql, params=()):
        if "FROM food_order" in sql:
            assert "'whatsapp'" in sql
            return FOOD | {
                "order_number": "ELAS-ABCD-1",
                "order_id": "ABCD-1",
                "total_price": 10,
                "origin_channel": origin,
                "action": action,
                "payment_status": "authorised",
            }
        if "FROM restaurant_master" in sql:
            return {"rest_name": "Elai"}
        if "FROM delivery_summary" in sql:
            return {"customer_address": "1 High St, Salisbury"}
        if "FROM takeaway_summary" in sql:
            return {"pickup_time": NOW}
        if "FROM web_order_request" in sql:
            assert origin == "web"
            return {"address": {"display": "snapshot", "instructions": "ring"}}
        return None

    return one


async def test_whatsapp_delivery_view(monkeypatch):
    monkeypatch.setattr(customer_order_view, "one", _view_one("whatsapp"))
    monkeypatch.setattr(customer_order_view, "query", AsyncMock(return_value=[]))
    view = await customer_order_view.get_view("ELAS-ABCD-1")
    assert view["origin_channel"] == "whatsapp"
    assert view["delivery"]["address"] == "1 High St, Salisbury"
    assert view["support"]["whatsapp_available"] is True
    assert view["support"]["whatsapp_url"] == "https://wa.me/message/AIDICBLAE4KZH1"


async def test_whatsapp_takeaway_view_reads_takeaway_summary(monkeypatch):
    monkeypatch.setattr(customer_order_view, "one", _view_one("whatsapp", "takeaway"))
    monkeypatch.setattr(customer_order_view, "query", AsyncMock(return_value=[]))
    view = await customer_order_view.get_view("ELAS-ABCD-1")
    assert view["mode"] == "collection" and "pickup_time" in view


async def test_web_view_still_has_no_whatsapp_support(monkeypatch):
    monkeypatch.setattr(customer_order_view, "one", _view_one("web"))
    monkeypatch.setattr(customer_order_view, "query", AsyncMock(return_value=[]))
    view = await customer_order_view.get_view("ELAS-ABCD-1")
    assert view["origin_channel"] == "web"
    assert view["support"]["whatsapp_available"] is False
    assert "whatsapp_url" not in view["support"]
