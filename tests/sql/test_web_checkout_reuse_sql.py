"""web_checkout.resume() payment rule run as real SQL on the disposable local PostgreSQL cluster."""
from unittest.mock import AsyncMock

import pytest
from psycopg.rows import dict_row

from utils_common.web_ordering import web_checkout as checkout
from utils_common.web_ordering.common import WebError


@pytest.fixture
def threads(db, monkeypatch):
    db.execute("BEGIN")
    for thread in ("reuse-a", "reuse-b"):
        db.execute("INSERT INTO thread(thread_id,agent) VALUES (%s,'WEB')", (thread,))

    async def one(sql, params=()):
        with db.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, params).fetchone()

    monkeypatch.setattr(checkout, "one", one)
    monkeypatch.setattr(checkout, "session", AsyncMock(return_value={"rest_ref": "SFCS", "mode": "collection"}))
    monkeypatch.setattr(checkout.availability, "available", AsyncMock())
    yield db
    db.execute("ROLLBACK")


def order(db, number, thread, payment_status):
    db.execute(
        "INSERT INTO food_order(order_id,order_number,origin_channel,action,payment_status) VALUES (%s,%s,'web','takeaway',%s)",
        (number, number, payment_status),
    )
    db.execute(
        "INSERT INTO web_order_request(idempotency_key,thread_id,body_hash,order_number) VALUES (%s,%s,'hash',%s)",
        (number, thread, number),
    )


async def blocked(thread):
    try:
        await checkout.resume(thread, "W-KEY")
    except WebError as error:
        assert error.body["error"] == "payment_already_processed"
        return True
    return False


async def test_checkout_without_orders_resumes(threads):
    assert not await blocked("reuse-a")


async def test_unpaid_orders_keep_the_checkout_reusable(threads):
    order(threads, "SFCS-REUS-1", "reuse-a", "requires_payment")
    order(threads, "SFCS-REUS-2", "reuse-a", "requires_payment")
    assert not await blocked("reuse-a")


@pytest.mark.parametrize("status", ["requires_capture", "pay_at_rest", "succeeded"])
async def test_one_paid_order_retires_only_its_own_checkout(threads, status):
    order(threads, "SFCS-REUS-1", "reuse-a", "requires_payment")
    order(threads, "SFCS-REUS-2", "reuse-a", status)
    order(threads, "SFCS-REUS-3", "reuse-b", "requires_payment")
    assert await blocked("reuse-a")
    assert not await blocked("reuse-b")
