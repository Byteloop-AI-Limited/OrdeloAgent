"""
A rider starts or ends a shift (rider_master.is_in_shift): one rule for both channels (phase R5, D41, D53).
    . Deep module: one call hides the status gate (only status = 'active' may start a shift; Telegram sign-ups start
      'inactive') and the on-a-job check (nobody ends a shift during a delivery). The rule is one SQL function; this is the
      typed wrapper (CLAUDE.md, RPC pattern).
    . RPC is DEFINED in: ordelo_datamodels/availability/rider_shift.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        set_shift -> rider_set_shift(p_rider_id, p_on)
    . Callers: watomation/on_callback_wa_handler.handle_shift_availability (the WhatsApp shift question's Yes / No, texts
      unchanged) and the rider bot's /on (channels/telegram/rider/availability.py)
    . Uses client_ordelo_service (service-role only RPC) inside asyncio.to_thread
  Classes/Functions:
    . ShiftOutcome
    . set_shift
    . ON, OFF, NOT_ACTIVE, ON_JOB, NOT_FOUND (results)

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_set_shift (function, ordelo_datamodels/availability/rider_shift.sql): calls
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from config import client_ordelo_service

ON = "on"
OFF = "off"
NOT_ACTIVE = "not_active"
ON_JOB = "on_job"
NOT_FOUND = "not_found"
_RESULTS = frozenset({ON, OFF, NOT_ACTIVE, ON_JOB, NOT_FOUND})


@dataclass(frozen=True)
class ShiftOutcome:
    result: str  # on | off | not_active | on_job | not_found
    order_number: str | None = None  # on_job: the rider's current order
    status: str | None = None  # not_active: the rider's status


def _outcome(data: Any) -> ShiftOutcome:
    if not isinstance(data, dict) or data.get("result") not in _RESULTS:
        raise RuntimeError(f"unexpected rider_set_shift response: {data!r}")
    return ShiftOutcome(data["result"], data.get("order_number"), data.get("status"))


async def set_shift(rider_id: str, on: bool) -> ShiftOutcome:
    """Start (on=True) or end a rider's shift. Start: 'on', or 'not_active' (nothing written). End: 'off', or 'on_job'
    (nothing written). 'not_found' for an unknown rider."""
    resp = await asyncio.to_thread(
        lambda: client_ordelo_service.rpc("rider_set_shift", {"p_rider_id": rider_id, "p_on": on}).execute()
    )
    return _outcome(resp.data)
