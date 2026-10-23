"""Telegram adapter for RiderMessenger, on the rider bot (@ByteloopRidersBot).

Mapping (D45, D49, D50):
    say             send_message, WhatsApp-style text -> HTML (formatting.wa_to_html); header in bold on its own line, footer
                    in italics; LinkButton -> one inline URL button; reply_to (same chat only) -> ReplyParameters
    send_place      send_venue (named pin) or send_location (blank name, like the drop-off pin)
    request_location  send_message with a one-time "📍 Share current location" reply keyboard
    send_contact    send_contact
    mark            set_message_reaction 👍 / 👎 (Telegram's reaction set has no ✅ / ❌)
    job_card        send_message with Pickup / Dropoff / Contact inline buttons (RiderJobAction 'rj1:<dispatch_id>:pk|dr|cc')
    offer_job       send_message with Accept / Decline inline buttons (RiderOffer 'ro1:<dispatch_id>:a|d')
    offer_closed    edit the offer in place, buttons removed; NO new message (an edit does not buzz the phone)
Bot API rules from the restaurant bot apply (plans/telegram-rest-admin-scaffold-plan.md rule 3): the shared session has a
10 s timeout; callers decide whether a failed send matters.
"""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, ReplyParameters
from loguru import logger

from channels.telegram.keyboards import location_request_kb, rider_job_card_kb, rider_offer_kb

from .formatting import wa_to_html
from .models import ContactCard, JobOffer, LinkButton, MsgRef, OfferClosedReason, Place, parse_tg_ref, tg_ref

REACTION_OK = "👍"
REACTION_FAIL = "👎"

CLOSED_TEXT: dict[str, str] = {
    "taken": "❌ Taken by another rider · <b>{order}</b>",
    "expired": "⌛ Offer expired · <b>{order}</b>",
    "cancelled": "🚫 Order cancelled · <b>{order}</b>",
    "assigned": "✅ The job is yours · <b>{order}</b>",
    "accepted": "👍 Accepted · <b>{order}</b>\nWaiting for confirmation…",
    "declined": "Declined · <b>{order}</b>",
    "gone": "This job is no longer available · <b>{order}</b>",
}


class TelegramRiderMessenger:
    channel = "telegram"

    def __init__(self, bot: Bot, tcid: int):
        self.bot = bot
        self.tcid = tcid

    def _reply(self, ref: MsgRef | None) -> ReplyParameters | None:
        parsed = parse_tg_ref(ref)
        if parsed is None or parsed[0] != self.tcid:
            return None
        return ReplyParameters(message_id=parsed[1], allow_sending_without_reply=True)

    async def say(self, text, *, reply_to=None, header=None, footer=None, link: LinkButton | None = None) -> MsgRef:
        body = wa_to_html(text)
        if header:
            body = f"<b>{escape(header, quote=False)}</b>\n{body}"
        if footer:
            body = f"{body}\n<i>{escape(footer, quote=False)}</i>"
        markup = (
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=link.title, url=link.url)]]) if link else None
        )
        sent = await self.bot.send_message(self.tcid, body, reply_parameters=self._reply(reply_to), reply_markup=markup)
        return tg_ref(self.tcid, sent.message_id)

    async def send_place(self, place: Place, *, reply_to=None) -> MsgRef:
        reply = self._reply(reply_to)
        if place.name and place.name.strip():
            sent = await self.bot.send_venue(
                self.tcid, place.latitude, place.longitude, title=place.name, address=place.address or " ",
                reply_parameters=reply,
            )
        else:
            sent = await self.bot.send_location(self.tcid, place.latitude, place.longitude, reply_parameters=reply)
        return tg_ref(self.tcid, sent.message_id)

    async def request_location(self, prompt: str) -> MsgRef:
        sent = await self.bot.send_message(self.tcid, wa_to_html(prompt), reply_markup=location_request_kb())
        return tg_ref(self.tcid, sent.message_id)

    async def send_contact(self, contact: ContactCard) -> MsgRef:
        sent = await self.bot.send_contact(self.tcid, phone_number=contact.phone, first_name=contact.name)
        return tg_ref(self.tcid, sent.message_id)

    async def mark(self, ref: MsgRef, ok: bool) -> None:
        parsed = parse_tg_ref(ref)
        if parsed is None or parsed[0] != self.tcid:
            return
        await self.bot.set_message_reaction(
            self.tcid, parsed[1], reaction=[ReactionTypeEmoji(emoji=REACTION_OK if ok else REACTION_FAIL)]
        )

    async def job_card(self, header: str, text: str, dispatch_id: int) -> MsgRef:
        body = f"<b>{escape(header, quote=False)}</b>\n{wa_to_html(text.strip())}"
        sent = await self.bot.send_message(self.tcid, body, reply_markup=rider_job_card_kb(dispatch_id))
        return tg_ref(self.tcid, sent.message_id)

    async def offer_job(self, offer: JobOffer) -> MsgRef:
        body = f"<b>{escape(offer.header, quote=False)}</b>\n{wa_to_html(offer.text.strip())}"
        sent = await self.bot.send_message(self.tcid, body, reply_markup=rider_offer_kb(offer.dispatch_id))
        return tg_ref(self.tcid, sent.message_id)

    async def offer_closed(self, ref: MsgRef | None, order_number: str, reason: OfferClosedReason) -> None:
        parsed = parse_tg_ref(ref)
        if parsed is None or parsed[0] != self.tcid:
            logger.warning(f"telegram[rider]: offer_closed without a Telegram offer ref ({ref!r}); nothing to edit")
            return
        text = CLOSED_TEXT[reason].format(order=escape(order_number or "", quote=False))
        if not order_number:  # the offer row is gone and its order unknown: no empty "· <b></b>"
            text = text.replace(" · <b></b>", "")
        try:
            await self.bot.edit_message_text(text, chat_id=self.tcid, message_id=parsed[1], reply_markup=None)
        except TelegramBadRequest as e:  # already edited, or deleted by the rider: the buttons are gone either way
            logger.info(f"telegram[rider]: offer {ref} not edited: {e.message}")
