"""Tests for OwnTracks location Pydantic model behaviour.

Covers topic parsing, timestamp-derived fields, literal validation, and ID
defaulting without needing any DB or webhook runtime.

Key Functions:
  - test_location_parses_topic_into_rider_recipient_order
  - test_location_sets_dt_and_dtts_from_tst
  - test_location_rejects_invalid_event_type_literal
  - test_short_uuid_returns_urlsafe_id
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from ordelo_datamodels.location_pymodels import Location, short_uuid


def test_location_parses_topic_into_rider_recipient_order() -> None:
    loc = Location(
        topic="owntracks/rider-1/447400000000-ORD123",
        rider_id="ignored",
        recipient="ignored",
        order_number="ignored",
        lat=51.5,
        lon=-0.12,
        tst=1_768_000_000,
        tid="aa",
    )

    assert loc.rider_id == "rider-1"
    assert loc.recipient == "447400000000"
    assert loc.order_number == "ORD123"


def test_location_sets_dt_and_dtts_from_tst() -> None:
    loc = Location(
        topic="owntracks/rider/recipient-ORD123",
        rider_id="rider",
        recipient="recipient",
        order_number="ORD123",
        lat=51.5,
        lon=-0.12,
        tst=1_768_000_000,
        tid="aa",
    )

    expected = datetime.fromtimestamp(1_768_000_000, tz=timezone.utc)
    assert loc.dt == expected.date()
    assert loc.dtts == expected
    assert isinstance(loc.dt, date)


def test_location_rejects_invalid_event_type_literal() -> None:
    with pytest.raises(ValidationError):
        Location(
            topic="owntracks/rider/recipient-ORD123",
            rider_id="rider",
            recipient="recipient",
            order_number="ORD123",
            lat=51.5,
            lon=-0.12,
            tst=1_768_000_000,
            tid="aa",
            t="invalid",
        )


def test_short_uuid_returns_urlsafe_id() -> None:
    value = short_uuid()
    assert value
    assert "=" not in value
