"""A checkout is reusable until one of its orders is paid; the key of a paid order is never replayed."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from tests.utils_common.web_ordering.test_payment_routing_compatibility import request
from utils_common.web_ordering import web_checkout as checkout
from utils_common.web_ordering.common import WebError
from watomation.routers import web_hooks

META = {"thread_id": "WEB-t", "cust_id": "W-KEY", "rest_ref": "ELAS", "mode": "collection", "town_slug": "salisbury", "address": None}


@pytest.fixture
def checkout_session(monkeypatch):
    monkeypatch.setattr(checkout, "session", AsyncMock(return_value=META))
    monkeypatch.setattr(checkout.availability, "available", AsyncMock(return_value={}))


async def test_unpaid_checkout_resumes_and_rechecks_availability(monkeypatch, checkout_session):
    paid = AsyncMock(return_value=None)
    monkeypatch.setattr(checkout, "one", paid)
    await checkout.resume("WEB-t", "W-KEY")
    assert paid.await_args.args[1] == ("WEB-t",)
    checkout.availability.available.assert_awaited_once_with("ELAS", "collection")


async def test_paid_checkout_is_not_resumed(monkeypatch, checkout_session):
    monkeypatch.setattr(checkout, "one", AsyncMock(return_value={"order_number": "ELAS-ABCD-1"}))
    with pytest.raises(WebError) as caught:
        await checkout.resume("WEB-t", "W-KEY")
    assert (caught.value.status, caught.value.body) == (409, {"error": "payment_already_processed"})


async def test_expired_session_is_reported_before_payment_state(monkeypatch):
    monkeypatch.setattr(checkout, "session", AsyncMock(side_effect=WebError("no_checkout_session", 409)))
    paid = AsyncMock()
    monkeypatch.setattr(checkout, "one", paid)
    with pytest.raises(WebError) as caught:
        await checkout.resume("WEB-t", "W-KEY")
    assert caught.value.body["error"] == "no_checkout_session"
    paid.assert_not_awaited()


@pytest.mark.parametrize("paid,status,body", [
    (None, 200, {"ok": True}),
    ({"order_number": "ELAS-ABCD-1"}, 409, {"error": "payment_already_processed"}),
])
def test_resume_route(monkeypatch, checkout_session, paid, status, body):
    monkeypatch.setenv("ORDELO_WEB_KEY", "k" * 48)
    monkeypatch.setattr(checkout, "one", AsyncMock(return_value=paid))
    app = FastAPI()
    app.include_router(web_hooks.router, prefix="/web")

    @app.exception_handler(WebError)
    async def error(request, exc):
        return JSONResponse(exc.body, status_code=exc.status)

    response = TestClient(app).post(
        "/web/checkout-sessions/resume",
        json={"thread_id": "WEB-t", "cust_id": "W-KEY"},
        headers={"X-Ordelo-Web-Key": "k" * 48},
    )
    assert (response.status_code, response.json()) == (status, body)


class ReplayCursor:
    """The stored attempt, its order's payment status and its saved quote."""

    def __init__(self, payment_status, executed):
        self.payment_status, self.executed, self.sql = payment_status, executed, ""

    async def execute(self, sql, params=()):
        self.sql = sql
        self.executed.append(sql)

    async def fetchone(self):
        if "FROM food_order" in self.sql:
            return {"payment_status": self.payment_status}
        if "SELECT quote" in self.sql:
            return {"quote": {"order_number": "ELAS-ABCD-1", "total": 3.0}}
        if "FROM web_order_request" in self.sql:
            return {"thread_id": "WEB-t", "order_number": "ELAS-ABCD-1", "body_hash": checkout.fingerprint(request(), None), "quote": None}
        return None


@pytest.fixture
def replay(monkeypatch, checkout_session):
    executed = []

    def run(payment_status, req=None):
        @asynccontextmanager
        async def context(value=None, **kwargs):
            yield value

        cursor = ReplayCursor(payment_status, executed)
        conn = SimpleNamespace(transaction=lambda: context(), cursor=lambda **kwargs: context(cursor))
        pool = SimpleNamespace(connection=lambda: context(conn))
        monkeypatch.setattr(checkout, "pg_settings", SimpleNamespace(get_pool=AsyncMock(return_value=pool)))
        monkeypatch.setattr(checkout.order_access, "issue", AsyncMock(return_value="token"))
        monkeypatch.setattr(checkout, "web_return_urls", AsyncMock(return_value={}))
        return checkout.create(req or request(), "key")

    run.executed = executed
    return run


async def test_retry_before_payment_returns_the_same_order(replay):
    result = await replay("requires_payment")
    assert result["order_number"] == "ELAS-ABCD-1"
    assert not any("INSERT" in sql for sql in replay.executed)


@pytest.mark.parametrize("payment_status", ["requires_capture", "pay_at_rest", "succeeded", "canceled", None])
async def test_key_of_a_paid_order_is_not_replayed(replay, payment_status):
    with pytest.raises(WebError) as caught:
        await replay(payment_status)
    assert (caught.value.status, caught.value.body) == (409, {"error": "payment_already_processed"})
    checkout.order_access.issue.assert_not_awaited()
    assert not any("INSERT" in sql for sql in replay.executed)


async def test_changed_basket_is_still_a_conflict_after_payment(replay):
    changed = request()
    changed.order_items[0].quantity = 2
    with pytest.raises(WebError) as caught:
        await replay("requires_capture", changed)
    assert caught.value.body["error"] == "idempotency_conflict"
