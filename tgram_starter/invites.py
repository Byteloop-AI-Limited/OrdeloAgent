"""In-memory stand-in for the `tgram_invites` table. Lost on restart - that's fine for a test.

Equivalent SQL when you make it real:

    create table tgram_invites (
      invite_code      text primary key,          -- random, single use (store a hash in prod)
      phone_number     text not null,             -- E.164, who we intended it for
      status           text not null default 'pending',  -- pending | claimed | expired | revoked
      created_at       timestamptz not null default now(),
      expires_at       timestamptz not null,
      claimed_at       timestamptz,
      telegram_user_id bigint,                    -- from_user.id  (the person)
      telegram_chat_id bigint,                    -- chat.id       (where we message them)
      telegram_username text,                     -- mutable, display only
      first_name       text,
      language_code    text,
      phone_verified   boolean default false      -- true if they shared their own contact and it matched
    );
"""
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

TGRAM_INVITES: dict[str, dict] = {}  # key = invite_code
_lock = threading.Lock()  # claim must be atomic; use `update ... where status='pending'` in SQL


def normalize_phone(phone: str) -> str:
    """Digits only, so '+44 7700 900123' == '447700900123'. Good enough for a demo."""
    return "".join(ch for ch in phone if ch.isdigit())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_invite(phone_number: str, ttl_hours: int = 48) -> dict:
    # token_urlsafe(9) -> 12 chars, only [A-Za-z0-9_-] which is what /start payloads allow (max 64).
    code = secrets.token_urlsafe(9)
    row = {
        "invite_code": code,
        "phone_number": normalize_phone(phone_number),
        "status": "pending",
        "created_at": _now(),
        "expires_at": _now() + timedelta(hours=ttl_hours),
        "claimed_at": None,
        "telegram_user_id": None,
        "telegram_chat_id": None,
        "telegram_username": None,
        "first_name": None,
        "language_code": None,
        "phone_verified": False,
    }
    with _lock:
        TGRAM_INVITES[code] = row
    return row


def invite_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={code}"


def claim_invite(code: str, *, user_id: int, chat_id: int, username: Optional[str],
                 first_name: Optional[str], language_code: Optional[str]) -> tuple[str, Optional[dict]]:
    """Returns (result, row). result: ok | unknown | used | expired | revoked."""
    with _lock:
        row = TGRAM_INVITES.get(code)
        if row is None:
            return "unknown", None
        if row["status"] == "claimed":
            # Same person pressing /start twice is harmless; anyone else is rejected.
            return ("ok" if row["telegram_user_id"] == user_id else "used"), row
        if row["status"] == "revoked":
            return "revoked", row
        if row["expires_at"] < _now():
            row["status"] = "expired"
            return "expired", row
        row.update(status="claimed", claimed_at=_now(), telegram_user_id=user_id,
                   telegram_chat_id=chat_id, telegram_username=username,
                   first_name=first_name, language_code=language_code)
        return "ok", row


def find_by_telegram_user(user_id: int) -> Optional[dict]:
    """Identity lookup used by handlers: who (in Ordelo terms) is this Telegram user?"""
    for row in TGRAM_INVITES.values():
        if row["status"] == "claimed" and row["telegram_user_id"] == user_id:
            return row
    return None


def mark_phone_verified(user_id: int, shared_phone: str) -> bool:
    row = find_by_telegram_user(user_id)
    if row and normalize_phone(shared_phone) == row["phone_number"]:
        row["phone_verified"] = True
        return True
    return False


def revoke(code: str) -> bool:
    with _lock:
        row = TGRAM_INVITES.get(code)
        if row and row["status"] == "pending":
            row["status"] = "revoked"
            return True
        return False
