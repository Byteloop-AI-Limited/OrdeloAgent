"""Channel-neutral values passed to and returned by a RiderMessenger (ordelo/rider_messaging/port.py).

MsgRef is OPAQUE to callers (the agent stores it in graph state as reply_to_msg_id / latest_wa_msg_id and hands it back):
    WhatsApp  the raw wamid, exactly as pywa returns it ('wamid.HBgM...'), so checkpoints of jobs that are already running
              keep working unchanged when the agent switches to the messenger (D45)
    Telegram  'tg:<tcid>:<message_id>'
Only the adapters look inside; a reference from the other channel is ignored (a dispatch never changes channel, D44).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, NewType

MsgRef = NewType("MsgRef", str)

Channel = Literal["whatsapp", "telegram"]
# Why an offer stops being open for this rider. WhatsApp sends text only for 'taken' (today's missed-offer message);
# Telegram edits the offer in place for every reason and removes its buttons (D49).
OfferClosedReason = Literal["taken", "expired", "cancelled", "assigned", "accepted", "declined", "gone"]

# The three buttons under the delivery instructions (job card): pickup pin, drop-off pin, customer contact.
JOB_CARD_ACTIONS: dict[str, tuple[str, str]] = {
    # code: (button title, what the rider "says" to the agent when tapping it; identical on both channels)
    "pk": ("Pickup Location", "Send me the pickup location"),
    "dr": ("Dropoff Location", "Send me the dropoff location"),
    "cc": ("Contact Customer", "I cannot reach customer, please send me customer contact."),
}

CANCEL_YES_TITLE = "Yes, cancel job"
CANCEL_NO_TITLE = "No, keep it"
CANCEL_CONFIRM_TEXT = "Do you want to cancel this job? It will be offered to other riders and you won't be offered it again."
CANCEL_TAP_RE = re.compile(r"\[cancel-confirm:(?P<token>[0-9a-f]{8}):(?P<answer>yes|no)\]")


def cancel_tap_text(token: str, answer: Literal["yes", "no"]) -> str:
    return f"[cancel-confirm:{token}:{answer}]"


CHANNEL_NAMES = {"whatsapp": "WhatsApp", "telegram": "Telegram"}


def wrong_channel_text(order_number: str | None, job_channel: str) -> str:
    """D44: a rider wrote on the other app during a job. The message is not passed to the agent; this is the reply."""
    job = f"*{order_number}*" if order_number else "job"
    return f"Your current job {job} is on {CHANNEL_NAMES.get(job_channel, job_channel)}. Please reply there."


def on_telegram_text(bot_username: str | None = None) -> str:
    """R5: a Telegram rider (rider_master.channel 'telegram') with no job wrote on WhatsApp. Their offers, breaks (/off, /on)
    and shift status (/shift) are on the rider bot, so the WhatsApp shift question is not used for them (D53)."""
    where = f"t.me/{bot_username}" if bot_username else "the Byteloop riders bot on Telegram"
    return f"Your rider messages are on Telegram now: {where}. Send /shift there to see your status, or /off to take a break."


_TG_PREFIX = "tg:"


def tg_ref(tcid: int, message_id: int) -> MsgRef:
    return MsgRef(f"{_TG_PREFIX}{tcid}:{message_id}")


def parse_tg_ref(ref: str | None) -> tuple[int, int] | None:
    """(tcid, message_id) for a Telegram reference, None for anything else (WhatsApp ids, None, garbage)."""
    if not ref or not ref.startswith(_TG_PREFIX):
        return None
    try:
        tcid, mid = ref[len(_TG_PREFIX):].rsplit(":", 1)
        return int(tcid), int(mid)
    except ValueError:
        return None


def is_tg_ref(ref: str | None) -> bool:
    return parse_tg_ref(ref) is not None


@dataclass(frozen=True)
class Place:
    """A map pin: pickup (restaurant) or drop-off (customer). name may be blank (' ') as the drop-off pin is today."""

    latitude: float
    longitude: float
    name: str | None = None
    address: str | None = None


@dataclass(frozen=True)
class ContactCard:
    """A phone contact to hand to the rider (the customer, for a WhatsApp-origin order)."""

    name: str
    phone: str  # digits only


@dataclass(frozen=True)
class LinkButton:
    """One URL button under a message (e.g. 'Start live tracking')."""

    title: str
    url: str


@dataclass(frozen=True)
class JobOffer:
    """A delivery offer to one rider. header / text are written once, in WhatsApp style (*bold*), as today."""

    dispatch_id: int
    order_number: str
    header: str
    text: str
    footer: str = "♾️ Byteloop AI"
    notice: str | None = None
