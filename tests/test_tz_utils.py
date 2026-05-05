from datetime import datetime, timezone

from utils_common.tz_utils import UK_TZ, fmt_uk_time, parse_db_iso, to_uk_epoch


def test_winter_gmt_no_offset():
    # 2026-01-15 12:00 UTC → 12:00 PM UK (GMT, +00:00)
    assert fmt_uk_time("2026-01-15T12:00:00Z") == "12:00 PM"


def test_summer_bst_plus_one():
    # 2026-07-15 12:00 UTC → 1:00 PM UK (BST, +01:00)
    assert fmt_uk_time("2026-07-15T12:00:00Z") == "1:00 PM"


def test_bst_spring_forward_boundary():
    # 2026-03-29 00:30 UTC → 12:30 AM UK (still GMT before 01:00 jump)
    assert fmt_uk_time("2026-03-29T00:30:00Z") == "12:30 AM"


def test_gmt_fall_back_boundary():
    # 2026-10-25 01:30 UTC → 1:30 AM UK (already GMT after 01:00 fall-back)
    assert fmt_uk_time("2026-10-25T01:30:00Z") == "1:30 AM"


def test_no_leading_zero():
    assert fmt_uk_time("2026-01-15T09:05:00Z") == "9:05 AM"


def test_accepts_datetime_input():
    dt = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert fmt_uk_time(dt) == "1:00 PM"


def test_parse_db_iso_handles_trailing_z():
    dt = parse_db_iso("2026-01-15T12:00:00Z")
    assert dt.tzinfo is not None
    assert dt == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def test_to_uk_epoch_summer():
    e = to_uk_epoch("2026-07-15T12:00:00Z")
    assert datetime.fromtimestamp(e, tz=UK_TZ).strftime("%H:%M") == "13:00"
