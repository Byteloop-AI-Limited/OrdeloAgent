"""Hash-only, expiring guest order grants. An order number grants no access."""

import hashlib
import re
import secrets
from .common import RESTAURANTS, WebError, one, query

TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def digest(token):
    """Validate a 43-character URL-safe token and return its SHA-256 bytes.

    Malformed tokens raise unauthorised (401) before any database lookup.
    """
    if not TOKEN.fullmatch(token or ""):
        raise WebError("unauthorised", 401)
    return hashlib.sha256(token.encode()).digest()


async def issue(order_number):
    """Persist a hash-only page grant for a web order and return its raw secret.

    Expiry is 30 days after order creation, not after grant issuance. Each call
    creates a new grant; non-web or absent orders raise not_found (404).
    """
    token = secrets.token_urlsafe(32)
    rows = await query(
        """INSERT INTO order_access_grant(order_number,kind,secret_hash,expires_at)
        SELECT order_number,'page_token',%s,order_dtts+interval '30 days' FROM food_order
        WHERE order_number=%s AND origin_channel='web' RETURNING id""",
        (digest(token), order_number),
    )
    if not rows:
        raise WebError("not_found", 404)
    return token


async def issue_for_whatsapp(order_number, recipient):
    """Mint a full page grant for a paid WhatsApp order and return its raw secret.

    404 unknown order or restaurant not in RESTAURANTS; 409 web order (its link
    comes from checkout) or unpaid order; 403 recipient mismatch. Every call
    creates a new grant (no cap). Returns (token, expires_at).
    """
    order = await one(
        "SELECT origin_channel,recipient,payment_status FROM food_order WHERE order_number=%s",
        (order_number,),
    )
    if not order or order_number.split("-")[0] not in RESTAURANTS:
        raise WebError("not_found", 404)
    if order["origin_channel"] == "web":
        raise WebError("web_order", 409)
    if order["payment_status"] == "requires_payment":
        raise WebError("not_paid", 409)
    if not secrets.compare_digest(str(order["recipient"] or ""), str(recipient or "")):
        raise WebError("forbidden", 403)
    token = secrets.token_urlsafe(32)
    rows = await query(
        """INSERT INTO order_access_grant(order_number,kind,secret_hash,expires_at)
        SELECT order_number,'page_token',%s,order_dtts+interval '30 days' FROM food_order
        WHERE order_number=%s AND origin_channel='whatsapp' AND recipient=%s
        AND payment_status<>'requires_payment' RETURNING id, expires_at""",
        (digest(token), order_number, recipient),
    )
    if not rows:
        raise WebError("not_found", 404)
    return token, rows[0]["expires_at"]


async def verify(token, order_number=None):
    """Return the order and detail level for an unexpired page-token grant.

    Raise unauthorised (401) for invalid/expired secrets and forbidden (403) if
    an optional order_number differs. Does not consume the reusable page token.
    """
    row = await one(
        """SELECT order_number,detail_level FROM order_access_grant
        WHERE secret_hash=%s AND kind='page_token' AND expires_at>now()""",
        (digest(token),),
    )
    if not row:
        raise WebError("unauthorised", 401)
    if order_number and row["order_number"] != order_number:
        raise WebError("forbidden", 403)
    return row
