"""
Customer keys (CONTEXT.md "Customer key", "Web customer key").

A customer key identifies the customer on an order: the WhatsApp number for a
WhatsApp order, or a synthetic W-id for a web order. A W-id is never a phone
number, so nothing may message or call it.

Functions:
  . is_web_customer_key - True for a W-id ('W' + 11 base32 characters)
  . new_web_customer_key - Mint a W-id
"""

import re
import secrets

_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
# Minted from base32 (below); recognised more loosely as W + 11 upper-case
# letters/digits. A WhatsApp number is all digits, so the two never overlap.
_WEB_CUSTOMER_KEY_RE = re.compile(r"W[A-Z0-9]{11}")


def is_web_customer_key(value: str | None) -> bool:
    """Return True when ``value`` is a web customer key (W-id, 12 characters)."""
    return bool(value) and _WEB_CUSTOMER_KEY_RE.fullmatch(value) is not None


def new_web_customer_key() -> str:
    """Mint a new W-id: 'W' + 11 random base32 characters (fits VARCHAR(12))."""
    return "W" + "".join(secrets.choice(_BASE32_ALPHABET) for _ in range(11))
