from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UK_TZ = ZoneInfo("Europe/London")


def parse_db_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _coerce(iso_or_dt: str | datetime) -> datetime:
    return parse_db_iso(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt


def to_utc_aware(iso_or_dt: str | datetime) -> datetime:
    """Coerce an ISO string or datetime into a tz-aware datetime safe to subtract.

    LangGraph state holds either shape for the same field: init_ordelo_graph writes
    DeliverySummary.pickup_time, which is a `datetime`, while the webhook paths write
    the ISO string straight from the payload. Calling parse_db_iso on the datetime
    raises TypeError, so anything doing arithmetic on a state timestamp must come
    through here rather than parsing directly.

    A naive value is assumed UTC, matching how these columns are written.
    """
    dt = _coerce(iso_or_dt)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def fmt_uk_time(iso_or_dt: str | datetime) -> str:
    return _coerce(iso_or_dt).astimezone(UK_TZ).strftime("%I:%M %p").lstrip("0")


def to_uk_epoch(iso_or_dt: str | datetime) -> int:
    return int(_coerce(iso_or_dt).astimezone(UK_TZ).timestamp())
