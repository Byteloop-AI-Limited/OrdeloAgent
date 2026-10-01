"""
Order references (plan M1).

The order reference is the 4-letter middle part of ``order_id`` (``REF-seq``)
and ``order_number`` (``RESTREF-REF-seq``).

  . A recipient ending in four digits (a WhatsApp number) keeps the legacy,
    phone-derived reference, so WhatsApp orders are unchanged.
  . Anything else (a W-id) gets four random letters from an alphabet without
    I, L or O, so the reference never depends on a phone number (D12).

Functions:
  . new_order_reference - Reference for a recipient and order date
  . is_phone_derived - Whether a recipient gets the legacy reference
"""

import secrets

from utils_common.order_management.customer_keys import is_web_customer_key
from utils_common.order_management.order_db_ops_new import create_order_reference

#: 23 letters: the alphabet without I, L and O, which are easy to misread.
RANDOM_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"


def is_phone_derived(recipient: str) -> bool:
    """True when ``recipient`` gets the legacy phone-derived reference."""
    if is_web_customer_key(recipient):
        return False
    last_four = recipient[-4:]
    return len(last_four) == 4 and last_four.isdigit()


def new_order_reference(recipient: str, order_dt: str) -> str:
    """Return the 4-letter order reference for ``recipient`` on ``order_dt``."""
    if is_phone_derived(recipient):
        return create_order_reference(recipient, order_dt)
    return "".join(secrets.choice(RANDOM_REFERENCE_ALPHABET) for _ in range(4))
