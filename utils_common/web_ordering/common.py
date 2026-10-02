"""R3 database helpers, launch restaurant registry and public error contract."""
from datetime import datetime, timezone
from psycopg.rows import dict_row
from config.pg_setting import pg_settings

# Evidence: payment-service/internal/config/config.go. Unknown refs fall back to
# ELAS there, so web checkout must reject them before contacting that service.
RESTAURANTS = {
    'ELAS': {'town': 'salisbury', 'phone': '01722656888'},
    'SFCS': {'town': 'salisbury', 'phone': '01722433714'},
    'BNAT': {'town': 'orpington', 'phone': '01689637476'},
}
MAX_ORDER_LINES = 20
LATE_PAYMENT_MINUTES = 35

class WebError(Exception):
    def __init__(self, error, status=422, **details):
        self.status, self.body = status, {'error': error, **details}
        super().__init__(error)

def utcnow():
    return datetime.now(timezone.utc)

def iso(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value

async def query(sql, params=()):
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall() if cur.description else []

async def one(sql, params=()):
    rows = await query(sql, params)
    return rows[0] if rows else None
