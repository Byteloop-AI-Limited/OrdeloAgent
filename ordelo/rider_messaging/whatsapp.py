"""WhatsApp adapter for RiderMessenger: the SAME pywa calls, with the SAME text, that the rider agent and hooks make today.

The rule (D45): switching a caller from `wa_client.<method>(...)` to the messenger must not change one byte the rider sees
on WhatsApp. So this adapter only maps arguments: text is passed through untouched, the job-offer payloads and the
missed-offer text are copied verbatim from watomation/routers/delivery_hooks.py (wa_send_delivery_dispatch_request_to_rider,
notify_missed_dispatches_hook). tests/ordelo/test_rider_messaging.py pins those shapes.
"""

from __future__ import annotations

import json
from typing import Any

from pywa.types import Button, ButtonUrl, Contact

from .models import ContactCard, JobOffer, LinkButton, MsgRef, OfferClosedReason, Place

REACTION_OK = "✅"
REACTION_FAIL = "❌"


def missed_offer_text(order_number: str) -> str:
    """Verbatim (whitespace included) from delivery_hooks.notify_missed_dispatches_hook."""
    return f"""
            Sorry, the order was picked up by another rider. Order number: *{order_number}*
            """


def _ref(sent: Any) -> MsgRef:
    return MsgRef(str(getattr(sent, "id", "") or ""))


def _wa_id(ref: MsgRef | None) -> str | None:
    """A WhatsApp reply target; a Telegram ref (or none) means 'no reply target'."""
    return None if not ref or str(ref).startswith("tg:") else str(ref)


class WhatsAppRiderMessenger:
    channel = "whatsapp"

    def __init__(self, wa_client: Any, phone: str):
        self.wa = wa_client
        self.phone = phone

    async def say(self, text, *, reply_to=None, header=None, footer=None, link: LinkButton | None = None) -> MsgRef:
        kwargs: dict[str, Any] = {"to": self.phone, "text": text, "reply_to_message_id": _wa_id(reply_to)}
        if header is not None:
            kwargs["header"] = header
        if footer is not None:
            kwargs["footer"] = footer
        if link is not None:
            kwargs["buttons"] = ButtonUrl(title=link.title, url=link.url)
        return _ref(await self.wa.send_message(**kwargs))

    async def send_place(self, place: Place, *, reply_to=None) -> MsgRef:
        return _ref(
            await self.wa.send_location(
                to=self.phone,
                latitude=place.latitude,
                longitude=place.longitude,
                name=place.name,
                address=place.address,
                reply_to_message_id=_wa_id(reply_to),
            )
        )

    async def request_location(self, prompt: str) -> MsgRef:
        return _ref(await self.wa.request_location(to=self.phone, text=prompt))

    async def send_contact(self, contact: ContactCard) -> MsgRef:
        return _ref(
            await self.wa.send_contact(
                to=self.phone,
                contact=Contact(
                    name=Contact.Name(formatted_name=contact.name, first_name=contact.name),
                    phones=[Contact.Phone(phone=contact.phone, wa_id=contact.phone, type="MOBILE")],
                ),
            )
        )

    async def mark(self, ref: MsgRef, ok: bool) -> None:
        wa_id = _wa_id(ref)
        if wa_id is None:
            return
        await self.wa.send_reaction(to=self.phone, emoji=REACTION_OK if ok else REACTION_FAIL, message_id=wa_id)

    async def offer_job(self, offer: JobOffer) -> MsgRef:
        def payload(status: str) -> str:
            return json.dumps(
                {
                    "command": "/dispatchResponse",
                    "order_number": offer.order_number,
                    "dispatch_id": offer.dispatch_id,
                    "status": status,
                    "rider_id": self.phone,
                }
            )

        return _ref(
            await self.wa.send_message(
                to=self.phone,
                header=offer.header,
                text=offer.text,
                footer=offer.footer,
                buttons=[
                    Button(title="Accept", callback_data=payload("accepted")),
                    Button(title="Decline", callback_data=payload("declined")),
                ],
            )
        )

    async def offer_closed(self, ref: MsgRef | None, order_number: str, reason: OfferClosedReason) -> None:
        # WhatsApp cannot edit the offer; today only 'taken' sends anything (notify_missed_dispatches_hook).
        if reason == "taken":
            await self.wa.send_message(to=self.phone, text=missed_offer_text(order_number))
