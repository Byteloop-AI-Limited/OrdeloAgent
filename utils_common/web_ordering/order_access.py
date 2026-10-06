"""Hash-only, expiring guest order grants. An order number grants no access."""

import hashlib
import re
import secrets
from .common import WebError, one, query

TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def digest(token):
    if not TOKEN.fullmatch(token or ""):
        raise WebError("unauthorised", 401)
    return hashlib.sha256(token.encode()).digest()


async def issue(order_number):
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


async def verify(token, order_number=None):
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
