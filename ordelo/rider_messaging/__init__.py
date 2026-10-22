"""Rider messaging: one interface for everything Ordelo says to a rider, on WhatsApp or Telegram (D45).

    from ordelo.rider_messaging import for_rider, Place
    messenger = await for_rider(rider_id)
    ref = await messenger.say("Heads up, the pickup time for order *X* has changed.", reply_to=previous_ref)

Files: port.py (the interface), models.py (MsgRef, Place, ContactCard, LinkButton, JobOffer), whatsapp.py / telegram.py
(adapters), formatting.py (WhatsApp-style text -> Telegram HTML), factory.py (which channel), fake.py (tests).
Phase R1 ships the module; the rider agent and hooks switch to it in phase R3 (plans/telegram-rider-bot-plan.md).
"""

from .factory import for_rider, messenger_for, use_messenger
from .models import ContactCard, JobOffer, LinkButton, MsgRef, Place, is_tg_ref, parse_tg_ref, tg_ref
from .port import RiderMessenger

__all__ = [
    "RiderMessenger",
    "for_rider",
    "messenger_for",
    "use_messenger",
    "MsgRef",
    "Place",
    "ContactCard",
    "LinkButton",
    "JobOffer",
    "tg_ref",
    "parse_tg_ref",
    "is_tg_ref",
]
