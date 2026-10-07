"""R3 database helpers, Salisbury/Orpington web registry and public error contract."""

import re
from datetime import datetime, timezone
from psycopg.rows import dict_row
from config.pg_setting import pg_settings

# Evidence: payment-service/internal/config/config.go. Unknown refs fall back to
# ELAS there, so web checkout must reject them before contacting that service.
RESTAURANTS = {
    "ELAS": {"town": "salisbury", "phone": "01722656888"},
    "SFCS": {"town": "salisbury", "phone": "01722433714"},
    "BNAT": {"town": "orpington", "phone": "01689637476"},
    "CRMS": {"town": "orpington", "phone": "01689838792"},
}
MAX_ORDER_LINES = 20
LATE_PAYMENT_MINUTES = 35


POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}")


def normalise_postcode(value):
    """Return a UK postcode as 'SP1 2AB' (upper case, one space), or None.

    None for empty input and anything that is not a full UK postcode shape.
    """
    compact = "".join((value or "").upper().split())
    if not POSTCODE_RE.fullmatch(compact):
        return None
    return compact[:-3] + " " + compact[-3:]


def postcode_sector(value):
    """Return the postcode sector without a space: outward code + first inward digit.

    'SP1 2AB' -> 'SP12'; 'SP10 1AA' -> 'SP101'. Empty string when too short.
    """
    compact = "".join((value or "").upper().split())
    return compact[:-2] if len(compact) >= 5 else ""


class WebError(Exception):
    def __init__(self, error, status=422, **details):
        """Build an API error with HTTP status and a public JSON error body.

        Extra keyword details are exposed to the caller; do not pass secrets.
        """
        self.status, self.body = status, {"error": error, **details}
        super().__init__(error)


def utcnow():
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def iso(value):
    """Serialize datetime-like values to ISO text; pass other values through."""
    return value.isoformat() if hasattr(value, "isoformat") else value


async def query(sql, params=()):
    """Execute parameterized SQL in a transaction using the public schema.

    Return dictionary rows for a result set, or an empty list for commands.
    Exceptions propagate and roll back the transaction. Each call owns its
    transaction; callers needing atomic multi-statement work must use a cursor.
    """
    pool = await pg_settings.get_pool()
    async with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute("SET LOCAL search_path = public")
        await cur.execute(sql, params)
        return await cur.fetchall() if cur.description else []


async def one(sql, params=()):
    """Execute SQL and return its first dictionary row, or None if empty."""
    rows = await query(sql, params)
    return rows[0] if rows else None
