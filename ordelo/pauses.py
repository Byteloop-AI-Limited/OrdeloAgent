"""
Pauses: a rider or a restaurant admin steps away until a MANDATORY end time (ADR 0013, D51).
    . Deep module: three calls hide the durations policy, the one-open-pause rule, extend-not-stack, expiry handling and
      the race between two /off taps. The rules are SQL functions; this is the typed wrapper (CLAUDE.md, RPC pattern).
    . Availability is computed, never flipped back: is_paused() in SQL is true only while now() < ends_at, and dispatch
      (get_available_riders) asks it directly. job_pause_sweep() only sends messages. So nothing here has to "turn a
      rider back on".
    . RPCs are DEFINED in: ordelo_datamodels/availability/pauses.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        pause   -> pause_start(p_audience, p_principal, p_scope, p_duration, p_via, p_by)
        resume  -> pause_end(p_audience, p_principal, p_scope, p_reason)
        current -> pause_current(p_audience, p_principal, p_scope)
        options -> pause_options(p_audience)
    . principal is the phone (digits only): rider_master.rider_id for riders, a restaurant_master.admins entry for admins;
      scope is None for riders, the rest_ref for an admin
    . Callers: the rider bot's /off, /on, /shift (channels/telegram/rider/availability.py, R5). Restaurant admins pause
      through t_admin_pause() (channels/telegram/admin_pauses.py, R6), which calls the same pause_start() in SQL with the
      last-admin guard. /pause-hooks/sweep reads nothing from here (the sweep payload carries what it needs)
    . Uses client_ordelo_service (service-role only RPCs) inside asyncio.to_thread
  Classes/Functions:
    . Pause, PauseOutcome
    . pause, resume, current, options
    . duration_label ('6h' -> '6 hours'), ends_text (a UK-time end for messages)
    . RIDER, REST_ADMIN (audiences)

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . pause_start (function, ordelo_datamodels/availability/pauses.sql): calls (name passed to a helper)
  . pause_end (function, ordelo_datamodels/availability/pauses.sql): calls (name passed to a helper)
  . pause_current (function, ordelo_datamodels/availability/pauses.sql): calls (name passed to a helper)
  . pause_options (function, ordelo_datamodels/availability/pauses.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from config import client_ordelo_service

RIDER = "rider"
REST_ADMIN = "rest_admin"
Audience = Literal["rider", "rest_admin"]

# pause_start: paused | extended | on_job | bad_duration | bad_audience | not_admin | not_allowed
# pause_end: resumed | not_paused | on_job
STARTED = frozenset({"paused", "extended"})


@dataclass(frozen=True)
class Pause:
    pause_id: int
    ends_at: datetime
    starts_at: datetime | None = None


@dataclass(frozen=True)
class PauseOutcome:
    result: str
    pause: Pause | None = None

    @property
    def is_paused(self) -> bool:
        return self.result in STARTED


def _ts(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _outcome(data: Any) -> PauseOutcome:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected pause RPC response: {data!r}")
    if data.get("pause_id") is not None and data.get("ends_at") is not None:
        return PauseOutcome(data["result"], Pause(int(data["pause_id"]), _ts(data["ends_at"]), _ts(data.get("starts_at"))))
    return PauseOutcome(data["result"])


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def pause(audience: Audience, principal: str, duration: str, *, scope: str | None = None,
                via: str = "telegram", by: str | None = None) -> PauseOutcome:
    """Pause from now for `duration` ('6h', '1d', '3d': only keys listed in ordelo_config PAUSE_DURATIONS_<AUDIENCE>).
    An open pause gets the new end time instead ('extended'); pauses never stack."""
    return _outcome(await _rpc("pause_start", {"p_audience": audience, "p_principal": principal, "p_scope": scope,
                                               "p_duration": duration, "p_via": via, "p_by": by}))


async def resume(audience: Audience, principal: str, *, scope: str | None = None, operator: bool = False) -> PauseOutcome:
    """End the current pause now. 'on_job' refuses a rider's own /on during delivery."""
    return _outcome(await _rpc("pause_end", {"p_audience": audience, "p_principal": principal, "p_scope": scope,
                                             "p_reason": "operator" if operator else "resumed"}))


async def current(audience: Audience, principal: str, *, scope: str | None = None) -> Pause | None:
    """The pause covering now(), or None."""
    out = _outcome(await _rpc("pause_current", {"p_audience": audience, "p_principal": principal, "p_scope": scope}))
    return out.pause if out.result == "paused" else None


async def options(audience: Audience) -> list[str]:
    """The duration keys this audience may pick, in ordelo_config order (the /off buttons); [] when /off is switched off."""
    data = await _rpc("pause_options", {"p_audience": audience})
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected pause_options response: {data!r}")
    return [str(k) for k in data]


def duration_label(key: str) -> str:
    """'6h' -> '6 hours', '1d' -> '1 day', '3d' -> '3 days' (button text)."""
    n, unit = int(key[:-1]), key[-1].lower()
    word = "hour" if unit == "h" else "day"
    return f"{n} {word}{'' if n == 1 else 's'}"


def ends_text(ends_at: datetime, now: datetime | None = None) -> str:
    """The end time as a person reads it, in UK time: '6:30 PM' today, 'tomorrow 6:30 PM', or 'Sat 24 Oct, 6:30 PM'."""
    from utils_common.tz_utils import UK_TZ

    end = ends_at.astimezone(UK_TZ)
    today = (now or datetime.now(UK_TZ)).astimezone(UK_TZ).date()
    clock = end.strftime("%I:%M %p").lstrip("0")
    if end.date() == today:
        return clock
    if (end.date() - today).days == 1:
        return f"tomorrow {clock}"
    return f"{end.strftime('%a')} {end.day} {end.strftime('%b')}, {clock}"
