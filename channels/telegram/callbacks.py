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
