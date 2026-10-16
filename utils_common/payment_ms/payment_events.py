"""
Payment events inbox (plan M2, ADR-0004).

Stripe posts ``checkout.session.completed`` straight to Ordelo's
``/payment-hooks/payment-complete``, unsigned (D23). This module turns that
body into a ``PaymentAuthorisedEvent`` and applies it at most once through the
``record_payment_authorised`` SQL function, which logs the event and moves the
order from ``requires_payment`` to ``requires_capture`` in one transaction.

  . The event id is Stripe's ``id``; bodies without one (restaurant-agents
    ``/paid3100``, the test route) use ``authorised:<order_id>``, so they are
    still de-duplicated per order.
  . Event types other than ``checkout.session.completed`` are ignored.
  . Only non-personal fields are stored in ``payment_event.payload``.

Functions/Classes:
  . PaymentAuthorisedEvent - parsed authorisation
  . PaymentOutcome - result of applying one
  . parse_payment_complete - body -> event (None when the type is ignored)
  . record_payment_authorised - apply an event via the SQL function

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . record_payment_authorised (function, ordelo_datamodels/payment/record_payment_authorised.sql): calls, calls (name passed to a helper)
(end of database objects)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from config import client_ordelo, logger

CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"

APPLIED = "applied"
DUPLICATE = "duplicate"
REJECTED_STATE = "rejected_state"
UNKNOWN_ORDER = "unknown_order"


@dataclass(frozen=True)
class PaymentAuthorisedEvent:
    provider_event_id: str
    order_id: str
    payment_intent_id: Optional[str] = None
    amount_pence: Optional[int] = None
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentOutcome:
    outcome: str
    order: Optional[dict] = None
    payment_status: Optional[str] = None

    @property
    def applied(self) -> bool:
        return self.outcome == APPLIED


def parse_payment_complete(body: dict[str, Any]) -> Optional[PaymentAuthorisedEvent]:
    """Parse a payment-complete body.

    Returns None for a Stripe event type other than checkout.session.completed.
    Raises ValueError when the body has no ``data.object.metadata.orderID``.
    """
    event_type = body.get("type")
    if event_type is not None and event_type != CHECKOUT_SESSION_COMPLETED:
        return None

    obj = (body.get("data") or {}).get("object") or {}
    order_id = (obj.get("metadata") or {}).get("orderID")
    if not order_id:
        raise ValueError("payment-complete body has no data.object.metadata.orderID")

    payment_intent = obj.get("payment_intent")
    if isinstance(payment_intent, dict):
        payment_intent = payment_intent.get("id")
    amount_total = obj.get("amount_total")

    provider_event_id = body.get("id") or f"authorised:{order_id}"
    payload = {
        "type": event_type,
        "session_id": obj.get("id"),
        "source": "stripe" if body.get("id") else "ordelo_or_test",
    }
    return PaymentAuthorisedEvent(
        provider_event_id=provider_event_id,
        order_id=order_id,
        payment_intent_id=payment_intent,
        amount_pence=amount_total if isinstance(amount_total, int) else None,
        payload=payload,
    )


async def record_payment_authorised(evt: PaymentAuthorisedEvent) -> PaymentOutcome:
    """Apply ``evt`` at most once. Raises if the database call itself fails."""
    response = await asyncio.to_thread(
        lambda: client_ordelo.rpc(
            "record_payment_authorised",
            {
                "p_provider_event_id": evt.provider_event_id,
                "p_order_id": evt.order_id,
                "p_payment_intent_id": evt.payment_intent_id,
                "p_amount_pence": evt.amount_pence,
                "p_payload": evt.payload,
            },
        ).execute()
    )
    result = response.data or {}
    outcome = PaymentOutcome(
        outcome=result.get("outcome", ""),
        order=result.get("order"),
        payment_status=result.get("payment_status"),
    )
    logger.info(
        f"payment event {evt.provider_event_id} order={evt.order_id}: {outcome.outcome}"
        + (f" (payment_status={outcome.payment_status})" if outcome.payment_status else "")
    )
    return outcome
