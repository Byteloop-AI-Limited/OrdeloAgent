"""Verify the `initData` string Telegram hands to a Mini App.

The page can read `Telegram.WebApp.initDataUnsafe` (the user's name/id) but ANYONE can fake that in a
browser. The server must only trust `initData` after checking Telegram's HMAC signature:

    secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)
    data_check_string = all received fields except `hash`, sorted by key, as "key=value" joined by "\\n"

Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(Exception):
    """initData is missing, malformed, forged or expired."""


def validate_init_data(init_data: str, bot_token: str, max_age: int = 3600, now: float | None = None) -> dict:
    if not init_data:
        raise InitDataError("missing initData")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("duplicate fields")
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad signature")

    # A valid signature proves Telegram issued it, not that it is recent. Reject stale (replayed) blobs.
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        raise InitDataError("missing auth_date") from None
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("initData expired")

    try:
        user = json.loads(fields["user"])
        user_id = int(user["id"])
    except (KeyError, ValueError, TypeError):
        raise InitDataError("missing user") from None
    return {"user": user, "user_id": user_id, "auth_date": auth_date, "fields": fields}
