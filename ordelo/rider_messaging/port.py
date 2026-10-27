"""The RiderMessenger interface: everything the rider agent, its tools and the delivery hooks need to SAY to a rider.

Design (plans/telegram-rider-bot-plan.md D45; ADR 0011 Amendment 3):
    . One messenger is bound to one rider on one channel; callers never pass a phone, chat id, client or keyboard.
      Build it with ordelo.rider_messaging.for_rider(rider_id) (R1) or for_dispatch(dispatch_id) (R3, channel fixed per
      dispatch, D44).
    . Text is written ONCE, in WhatsApp style (*bold*, _italic_), exactly as the callers write it today. The WhatsApp
      adapter passes it through unchanged (WhatsApp messages stay byte-identical); the Telegram adapter converts it to HTML.
    . Every send returns an opaque MsgRef (models.py) that may be handed back as reply_to / to mark() / to offer_closed().
    . Errors: adapters raise what their client raises (pywa / aiogram errors). Callers that must not fail on a send
      catch, as they do today.
    . Inbound (rider text, taps, contacts, locations) is NOT part of this interface: each channel's handler turns it into a
      domain call (respond_to_offer, the rider agent runner, WaLocation) and builds the messenger for the reply.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Channel, ContactCard, JobOffer, LinkButton, MsgRef, OfferClosedReason, Place


@runtime_checkable
class RiderMessenger(Protocol):
    channel: Channel

    async def say(
        self,
        text: str,
        *,
        reply_to: MsgRef | None = None,
        header: str | None = None,
        footer: str | None = None,
        link: LinkButton | None = None,
    ) -> MsgRef:
        """A text message, optionally threaded under reply_to, with an optional header/footer and one URL button."""
        ...

    async def send_place(self, place: Place, *, reply_to: MsgRef | None = None) -> MsgRef:
        """A map pin (pickup or drop-off)."""
        ...

    async def request_location(self, prompt: str) -> MsgRef:
        """Ask for the rider's CURRENT location with the channel's one-tap button; the reply arrives through the inbound
        location handler (WaLocation), not here."""
        ...

    async def send_contact(self, contact: ContactCard) -> MsgRef:
        """A phone contact card."""
        ...

    async def mark(self, ref: MsgRef, ok: bool) -> None:
        """React to one of the rider's messages: accepted (ok) or rejected (e.g. a confirmation code)."""
        ...

    async def job_card(self, header: str, text: str, dispatch_id: int) -> MsgRef:
        """The delivery instructions with the three job buttons (Pickup Location, Dropoff Location, Contact Customer).
        A tap reaches the rider agent as the rider's own words (models.JOB_CARD_ACTIONS)."""
        ...

    async def confirm_cancel(self, dispatch_id: int, token: str, text: str) -> MsgRef:
        """Send the cancellation confirmation buttons."""
        ...

    async def offer_job(self, offer: JobOffer) -> MsgRef:
        """A job offer with Accept / Decline. Store the returned ref (delivery_dispatch.channel_msg_ref, R4)."""
        ...

    async def offer_closed(self, ref: MsgRef | None, order_number: str, reason: OfferClosedReason) -> None:
        """The offer is no longer open for this rider (reason: taken, expired, cancelled, assigned, accepted, declined, gone).
        WhatsApp: today's text for 'taken' only, nothing otherwise. Telegram: edit the offer in place and remove its
        buttons, sending nothing new (D49)."""
        ...

    async def delete(self, ref: MsgRef | None) -> None:
        """Remove an older offer copy when supported by the channel."""
        ...
