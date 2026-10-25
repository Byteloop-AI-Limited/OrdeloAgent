"""Callback-data conventions for Ordelo Telegram bots.

One CallbackData subclass per action family, each with a short `prefix`. Payloads carry
opaque short refs, never authority: every handler re-checks the actor and current state
(ADR 0011 decision 5). Telegram limits callback_data to 64 BYTES after .pack().
"""

from typing import Literal

from aiogram.filters.callback_data import CallbackData

CALLBACK_DATA_MAX_BYTES = 64


def fits_callback_limit(data: CallbackData) -> bool:
    return 1 <= len(data.pack().encode()) <= CALLBACK_DATA_MAX_BYTES


class InviteDecision(CallbackData, prefix="inv"):
    """Confirm (y) or decline (n) linking this chat via an invite code, e.g. 'inv:Ab3_xY9kLm0Q:y'.

    The code is the invite's opaque secret; the claim still checks it atomically in the database.
    """

    code: str
    action: Literal["y", "n"]


class OrderAction(CallbackData, prefix="ord"):
    """A tap on an order card or kitchen receipt, e.g. 'ord:ELAS-CEKT-22:d:pk:15'.

    o: order number; t: 'd' delivery / 't' takeaway; a: 'acc' accept, 'dec' decline, 'pk' pickup
    time (order cards); 'rdy' food ready, 'adj' move pickup later, 'st' tap on the status badge (kitchen receipts;
    'st' changes nothing: it only redraws the receipt's copies from the database).
    m: minutes after the order time for 'pk'; +minutes over the ORIGINAL pickup (10 or 20) for 'adj'; 0 otherwise.
    Carries no authority: the database re-checks who tapped and the order's current state on every tap.
    """

    o: str
    t: Literal["d", "t"]
    a: Literal["acc", "dec", "pk", "rdy", "adj", "st"]
    m: int = 0


# ---- rider bot (bot_key 'rider'; plans/telegram-rider-bot-plan.md) ------------------------------------------------------


class RiderSignup(CallbackData, prefix="rsu"):
    """A sign-up choice on the rider bot, e.g. 'rsu:t:Salisbury' (town) or 'rsu:v:bike' (vehicle type).

    v is the chosen value as t_rider_choices() listed it. Carries no authority and no phone: t_rider_set_profile() finds
    the rider by the tapping person's from_user.id and accepts only values that are still listed (D39, D41).
    """

    s: Literal["t", "v"]
    v: str


class RiderOffer(CallbackData, prefix="ro1"):
    """Accept (a) or decline (d) a job offer on the rider bot, e.g. 'ro1:84217:a' (phase R4, D48).

    d is the delivery_dispatch id. Packing is serialisation, not authorisation: the handler checks that the tapping
    person's tuid is the dispatch's rider and that the offer is still open before calling respond_to_offer().
    """

    d: int
    a: Literal["a", "d"]


class RiderJobAction(CallbackData, prefix="rj1"):
    """A tap on a job-card button on the rider bot, e.g. 'rj1:84217:pk' (pickup pin), 'dr' (drop-off pin), 'cc' (customer
    contact). The handler checks the tapping person is the dispatch's rider and the dispatch thread is open, then gives the
    agent the same words a WhatsApp tap gives it (ordelo/rider_messaging/models.JOB_CARD_ACTIONS)."""

    d: int
    a: Literal["pk", "dr", "cc"]


class RiderPause(CallbackData, prefix="rp1"):
    """A break length picked under /off on the rider bot, e.g. 'rp1:6h' (phase R5, ADR 0013).

    k is a duration key as pause_options('rider') listed it. Carries no authority: the handler finds the rider by the
    tapping person's from_user.id, and pause_start() accepts only keys still listed in ordelo_config.
    """

    k: str


class AdminChannels(CallbackData, prefix="ac1"):
    """A channel choice under /channels on the restaurant bot: 't' Telegram only, 'w' WhatsApp only, 'b' both, e.g. 'ac1:t'.

    Carries no authority: the handler finds the admin record by the tapping person's from_user.id (t_admin_profile) and
    admin_set_channels() changes only that record.
    """

    c: Literal["t", "w", "b"]


class AdminPause(CallbackData, prefix="ap1"):
    """An alert-pause length picked under /off on the restaurant bot, e.g. 'ap1:1d' (phase R6, D52).

    k is a duration key as pause_options('rest_admin') listed it. Carries no authority: t_admin_pause() finds the
    restaurants and the admin phone by the tapping person's from_user.id and applies the last-admin guard.
    """

    k: str
