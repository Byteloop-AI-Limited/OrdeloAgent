"""P7 rider_agent uncovered tool coverage."""
from __future__ import annotations
from types import SimpleNamespace
from ordelo.agents import rider_agent
from ordelo.rider_messaging.fake import RecordingRiderMessenger


class _FakeWa:
    async def send_message(self, **kw): return None
    async def send_location(self, **kw): return None
    async def send_contact(self, **kw): return None
    async def send_reaction(self, **kw): return None


class _FakeCtx:
    def __init__(self):
        self.recipient = "R1"
        self.messenger = RecordingRiderMessenger(rider_id="R1")  # the tools talk through ctx.messenger since R3
        self.thread_id = "ORDELO-dispatch-10"
        self.client_ordelo = SimpleNamespace(
            table=lambda name: SimpleNamespace(
                select=lambda *a: SimpleNamespace(
                    eq=lambda *a: SimpleNamespace(
                        limit=lambda n: SimpleNamespace(
                            execute=lambda: SimpleNamespace(data=[{
                                "rest_lat": 51.5, "rest_lon": -0.1, "rest_name": "Elai", "rest_address": "1 St",
                                "customer_lat": 51.6, "customer_lon": -0.2, "customer_address": "2 St",
                                "customer_id": "4474", "cust_confirmation_code": 44,
                                "rest_confirmation_code": 11,
                            }])
                        )
                    )
                )
            )
        )


def _state(**o):
    s = {"order_number": "ELAS-ABCD-1", "dispatch_id": 10, "reply_to_msg_id": "msg1", "latest_wa_msg_id": "msg2", "rider_name": "Bas"}
    s.update(o)
    return s


def _runtime():
    return SimpleNamespace(context=_FakeCtx())


async def test_notify_food_ready_for_pickup():
    r = await rider_agent.notify_food_ready_for_pickup("Elai", _state(), "tc1", _runtime())
    assert r is not None


async def test_send_pickup_location():
    r = await rider_agent.send_pickup_location(_state(), "tc1", _runtime())
    assert r is not None


async def test_send_pickup_location_no_order_number():
    r = await rider_agent.send_pickup_location(_state(order_number=None), "tc1", _runtime())
    assert r is not None


async def test_send_dropoff_location():
    r = await rider_agent.send_dropoff_location(_state(), "tc1", _runtime())
    assert r is not None


async def test_send_dropoff_location_no_order_number():
    r = await rider_agent.send_dropoff_location(_state(order_number=None), "tc1", _runtime())
    assert r is not None


async def test_send_customer_contact_no_order_number():
    r = await rider_agent.send_customer_contact(_state(order_number=None), "tc1", _runtime())
    assert r is not None


async def test_capture_reason_for_cancel_before_pickup_no_dispatch():
    r = await rider_agent.capture_reason_for_cancel_before_pickup("reason", _state(dispatch_id=None), "tc1", _runtime())
    assert r is not None
