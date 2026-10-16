"""
Restaurant-facing notices on every channel (D28, D29): one call, WhatsApp AND Telegram, in parallel.
    . notify(notice) never raises; each channel fails alone (logged), so Telegram trouble can never stop WhatsApp
    . WhatsApp adapter: calls the EXISTING wa_senders functions with the arguments they take today (text/buttons unchanged);
      senders are looked up as `wa_senders.<name>` at call time, so tests that patch them keep working
    . Telegram adapter: channels/telegram/rest_admin (Receipts.send), built lazily from config.rest_admin_bot
      (the same Bot the FastAPI lifespan registry uses); hooks and agent tools have no `request.app`
    . Notices handled in this file: KitchenReceipt (rider accepted a delivery), TakeawayReceipt (pickup confirmed),
      AutoAccepted (confirmation timeout), RiderAlert (late pickup / slow delivery), DeliveryCompleted, Feedback
    . Mapping, notice -> WhatsApp call -> Telegram call:
        KitchenReceipt  -> wa_senders.admin_order_reciept(delivery_summary, rider_master) -> Receipts.send(order, dispatch_id)
        TakeawayReceipt -> wa_senders.takeaway_admin_order_receipt(order_number, pickup_time, rest_name, admins,
                                                                    restaurant_msg_id, rest_ref) -> Receipts.send(order)
        AutoAccepted    -> wa_senders.admin_auto_accept_notice(admins, order_number, pickup_display, pickup_minutes)
                           -> Notices.send(..., reply_to="card")
        RiderAlert      -> wa_senders.notify_rest_admins_rider_alert(phase=, order_number=, pickup_time=, rider_id=,
                                                                      rider_name=, rest_ref=, rest_admins=)
                           -> Notices.send(..., reply_to="receipt"), wording from wa_senders.rider_alert_text
        DeliveryCompleted -> wa_senders.admin_delivery_completed(order_number, rest_ref)
                           -> Notices.send(..., reply_to="receipt") + Receipts.refresh(order)
        Feedback        -> wa_senders.send_restaurant_feedback_notification(admin=, ...) once per admin
                           -> Notices.send(..., no reply target)
    . Callers: watomation/routers/delivery_hooks.py (delivery_inflight_graph_init_hook step 3 -> KitchenReceipt;
      _handle_restaurant_timedout -> AutoAccepted; _process_rider_pickup_alerts -> RiderAlert),
      watomation/routers/takeaway_hooks.py (pickup_time_updated_hook step 3 -> TakeawayReceipt;
      _handle_restaurant_timedout -> AutoAccepted), ordelo/agents/rider_agent.py (DeliveryCompleted),
      watomation/routers/customer_hooks.py (_notify_feedback_admins -> Feedback)
    . Tests inject fakes with `use_adapters(whatsapp=..., telegram=...)` (a context manager)
    . Sibling of customer_notifier.py. Overview: docs/telegram-layer.md
  Classes/Functions:
    . KitchenReceipt, TakeawayReceipt, AutoAccepted, RiderAlert, DeliveryCompleted, Feedback
    . notify
    . use_adapters
"""

import asyncio
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any, Literal, Protocol

from config import logger
from ordelo_datamodels.delivery_pymodels import DeliverySummary
from utils_common.tz_utils import fmt_uk_time, parse_db_iso
from utils_common.waba_utils import wa_senders

FEEDBACK_TEXT_LIMIT = 1500  # Telegram caps a message at 4096; the customer's words are clipped before escaping


@dataclass(frozen=True)
class KitchenReceipt:
    """A rider accepted a delivery (delivery_inflight INSERT). WhatsApp needs the two payload values it gets today."""

    delivery_summary: DeliverySummary
    rider_master: dict | None
    dispatch_id: int | None


@dataclass(frozen=True)
class TakeawayReceipt:
    """A takeaway's pickup time is confirmed. The arguments are exactly takeaway_admin_order_receipt's."""

    order_number: str
    pickup_time: str
    rest_name: str
    admins: list[str]
    restaurant_msg_id: str | None
    rest_ref: str | None


@dataclass(frozen=True)
class AutoAccepted:
    """The restaurant did not answer in time and the order was auto-accepted (delivery or takeaway)."""

    order_number: str
    order_type: Literal["delivery", "takeaway"]
    admins: list[str]
    pickup_display: str
    pickup_minutes: int
    rest_ref: str


@dataclass(frozen=True)
class RiderAlert:
    """A late-pickup / slow-delivery alert for the restaurant. The arguments are notify_rest_admins_rider_alert's."""

    phase: str
    order_number: str
    pickup_time: str
    rider_id: str
    rider_name: str | None
    rest_ref: str | None
    rest_admins: list[str] | None


@dataclass(frozen=True)
class DeliveryCompleted:
    """The rider entered the right customer code: the delivery is done."""

    order_number: str
    rest_ref: str


@dataclass(frozen=True)
class Feedback:
    """Customer feedback for a restaurant (no order card or receipt to reply to)."""

    admins: list[str]
    feedback_id: str
    restaurant_name: str
    rest_ref: str
    cust_id: str
    cust_name: str | None
    order_reference: str | None
    description: str
    received_at: datetime


Notice = KitchenReceipt | TakeawayReceipt | AutoAccepted | RiderAlert | DeliveryCompleted | Feedback


class _Adapter(Protocol):
    async def send(self, notice: Notice) -> None: ...


class _WhatsAppAdapter:
    async def send(self, notice: Notice) -> None:
        if isinstance(notice, KitchenReceipt):
            await wa_senders.admin_order_reciept(delivery_summary=notice.delivery_summary, rider_master=notice.rider_master)
        elif isinstance(notice, TakeawayReceipt):
            await wa_senders.takeaway_admin_order_receipt(
                order_number=notice.order_number,
                pickup_time=notice.pickup_time,
                rest_name=notice.rest_name,
                admins=notice.admins,
                restaurant_msg_id=notice.restaurant_msg_id,
                rest_ref=notice.rest_ref,
            )
        elif isinstance(notice, AutoAccepted):
            await wa_senders.admin_auto_accept_notice(
                notice.admins, notice.order_number, notice.pickup_display, notice.pickup_minutes
            )
        elif isinstance(notice, RiderAlert):
            await wa_senders.notify_rest_admins_rider_alert(
                phase=notice.phase,
                order_number=notice.order_number,
                pickup_time=notice.pickup_time,
                rider_id=notice.rider_id,
                rider_name=notice.rider_name,
                rest_ref=notice.rest_ref,
                rest_admins=notice.rest_admins,
            )
        elif isinstance(notice, DeliveryCompleted):
            await wa_senders.admin_delivery_completed(notice.order_number, notice.rest_ref)
        elif isinstance(notice, Feedback):
            await self._feedback(notice)
        else:
            raise TypeError(f"restaurant_notifier: no WhatsApp mapping for {type(notice).__name__}")

    @staticmethod
    async def _feedback(notice: Feedback) -> None:
        results = await asyncio.gather(
            *(
                wa_senders.send_restaurant_feedback_notification(
                    admin=admin,
                    feedback_id=notice.feedback_id,
                    restaurant_name=notice.restaurant_name,
                    cust_id=notice.cust_id,
                    cust_name=notice.cust_name,
                    order_reference=notice.order_reference,
                    description=notice.description,
                    received_at=notice.received_at,
                )
                for admin in notice.admins
            ),
            return_exceptions=True,
        )
        for admin, result in zip(notice.admins, results):
            if isinstance(result, Exception):
                logger.warning(f"Feedback notification failed for feedback_id={notice.feedback_id} admin={admin}")


def _bold(whatsapp_text: str) -> str:
    """WhatsApp *bold* text -> Telegram HTML (everything else escaped)."""
    return re.sub(r"\*(.+?)\*", r"<b>\1</b>", escape(whatsapp_text))


def rider_alert_html(notice: RiderAlert, now: datetime | None = None) -> str:
    """The Telegram text of a rider alert: the WhatsApp wording (wa_senders.rider_alert_text), recomputed the same way
    from the ACTUAL minutes to / past pickup."""
    now = now or datetime.now(timezone.utc)
    minutes_past = round((now - parse_db_iso(notice.pickup_time)).total_seconds() / 60)
    return _bold(wa_senders.rider_alert_text(
        notice.phase, notice.order_number, minutes_past, fmt_uk_time(notice.pickup_time), notice.rider_name or notice.rider_id
    ))


def feedback_html(notice: Feedback) -> str:
    desc = notice.description
    if len(desc) > FEEDBACK_TEXT_LIMIT:
        desc = desc[:FEEDBACK_TEXT_LIMIT] + "…"
    e = escape
    return (
        f"💬 <b>Customer feedback</b> {e(notice.feedback_id)}\n"
        f"Restaurant: {e(notice.restaurant_name)}\n"
        f"Customer: {e(notice.cust_name or 'Not provided')} ({e(notice.cust_id)})\n"
        f"Order reference: {e(notice.order_reference or 'Not provided')}\n"
        f"Description: {e(desc)}\n"
        f"Received (UTC): {notice.received_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )


class _TelegramAdapter:
    def __init__(self) -> None:
        self._receipts: Any = None
        self._notices: Any = None

    def _notices_for_bot(self):
        if self._notices is None:
            from channels.telegram.rest_admin.notices import Notices
            from config import rest_admin_bot
            from config.tgram_setting import REST_ADMIN_BOT_KEY

            self._notices = Notices(rest_admin_bot, REST_ADMIN_BOT_KEY)
        return self._notices

    def _receipts_for_bot(self):
        if self._receipts is None:  # lazy: importing config builds the bot, and tests never need it
            from channels.telegram.rest_admin.receipts import Receipts
            from config import rest_admin_bot
            from config.tgram_setting import REST_ADMIN_BOT_KEY

            self._receipts = Receipts(rest_admin_bot, REST_ADMIN_BOT_KEY)
        return self._receipts

    async def send(self, notice: Notice) -> None:
        from channels.telegram.rest_admin.order_cards import OrderRef

        if isinstance(notice, KitchenReceipt):
            await self._receipts_for_bot().send(OrderRef(notice.delivery_summary.order_number, "delivery"), notice.dispatch_id)
        elif isinstance(notice, TakeawayReceipt):
            await self._receipts_for_bot().send(OrderRef(notice.order_number, "takeaway"), None)
        elif isinstance(notice, AutoAccepted):
            text = (
                f"⏱ <b>{escape(notice.order_number)}</b> auto-accepted (no answer in time). "
                f"Pickup {escape(notice.pickup_display)} ({notice.pickup_minutes} min after order)."
            )
            await self._notices_for_bot().send(
                notice.rest_ref, text, notice="auto_accepted",
                order=OrderRef(notice.order_number, notice.order_type), reply_to="card",
            )
        elif isinstance(notice, RiderAlert):
            if not notice.rest_ref:
                raise ValueError(f"rider alert for {notice.order_number} has no rest_ref")
            await self._notices_for_bot().send(
                notice.rest_ref, rider_alert_html(notice), notice="rider_alert",
                order=OrderRef(notice.order_number, "delivery"), reply_to="receipt",
            )
        elif isinstance(notice, DeliveryCompleted):
            order = OrderRef(notice.order_number, "delivery")
            await self._notices_for_bot().send(
                notice.rest_ref, f"✅ Delivered — <b>{escape(notice.order_number)}</b>", notice="delivered",
                order=order, reply_to="receipt",
            )
            await self._receipts_for_bot().refresh(order)  # the receipt copies now say done
        elif isinstance(notice, Feedback):
            await self._notices_for_bot().send(notice.rest_ref, feedback_html(notice), notice="feedback")
        else:
            raise TypeError(f"restaurant_notifier: no Telegram mapping for {type(notice).__name__}")


_whatsapp: _Adapter = _WhatsAppAdapter()
_telegram: _Adapter = _TelegramAdapter()


@contextmanager
def use_adapters(*, whatsapp: _Adapter | None = None, telegram: _Adapter | None = None):
    """Test seam: swap either adapter for the duration of the block (the real one stays for a side left as None)."""
    global _whatsapp, _telegram
    saved = (_whatsapp, _telegram)
    _whatsapp, _telegram = whatsapp or _whatsapp, telegram or _telegram
    try:
        yield
    finally:
        _whatsapp, _telegram = saved


async def notify(notice: Notice) -> None:
    """Send the notice on WhatsApp and Telegram at the same time. Never raises."""
    wa, tg = _whatsapp, _telegram
    results = await asyncio.gather(wa.send(notice), tg.send(notice), return_exceptions=True)
    for channel, r in zip(("whatsapp", "telegram"), results):
        if isinstance(r, BaseException):
            logger.opt(exception=r).error(f"restaurant_notifier: {channel} {type(notice).__name__} failed")
