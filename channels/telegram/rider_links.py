"""
Rider bot identity: link a Telegram account to rider_master, register new riders, store their sign-up choices.
    . Thin async wrapper over SQL functions (RPCs). The rules live in the database, not here (CLAUDE.md, RPC pattern).
    . RPCs are DEFINED in: ordelo_datamodels/telegram/t_rider_onboarding.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        link        -> t_rider_link(p_tuid, p_tcid, p_phone, p_username, p_first_name)   link / move / register (D42)
        set_profile -> t_rider_set_profile(p_tuid, p_town, p_vehicle_type)              fill 'TBD' town / vehicle
        choices     -> t_rider_choices()                                                 towns + vehicle types to offer
        profile     -> t_rider_profile(p_tuid)                                           who this Telegram account is
    . Table behind them: rider_master (core/rider_master.sql): tuid authorises, tcid addresses (D25, D40)
    . Callers MUST have checked contact.user_id == from_user.id before link() (D39); the phone is never taken from text
    . Called by: channels/telegram/rider/router.py
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Overview and cross-reference table: docs/telegram-layer.md (section 6, rider bot rows)
  Classes/Functions:
    . RiderLink, RiderChoices, RiderProfile
    . link, set_profile, choices, profile

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_rider_link (function, ordelo_datamodels/telegram/t_rider_onboarding.sql): calls (name passed to a helper)
  . t_rider_set_profile (function, ordelo_datamodels/telegram/t_rider_onboarding.sql): calls (name passed to a helper)
  . t_rider_choices (function, ordelo_datamodels/telegram/t_rider_onboarding.sql): calls (name passed to a helper)
  . t_rider_profile (function, ordelo_datamodels/telegram/t_rider_onboarding.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from config import client_ordelo_service

# t_rider_link results: linked | relinked | already_linked | registered | tuid_taken | bad_phone
LINKED_RESULTS = frozenset({"linked", "relinked", "already_linked", "registered"})


@dataclass(frozen=True)
class RiderLink:
    """Outcome of t_rider_link / t_rider_set_profile / t_rider_profile (fields absent from a result stay None)."""

    result: str
    rider_id: str | None = None
    rider_name: str | None = None
    status: str | None = None
    town: str | None = None
    vehicle_type: str | None = None
    needs_profile: bool = False
    previous_tuid: int | None = None
    previous_username: str | None = None

    @property
    def is_linked(self) -> bool:
        return self.result in LINKED_RESULTS

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class RiderProfile:
    result: str  # ok | not_linked
    rider_id: str | None = None
    rider_name: str | None = None
    status: str | None = None
    town: str | None = None
    vehicle_type: str | None = None
    channel: str | None = None
    is_in_shift: bool | None = None
    tcid: int | None = None
    needs_profile: bool = False

    @property
    def is_linked(self) -> bool:
        return self.result == "ok"


@dataclass(frozen=True)
class RiderChoices:
    towns: list[str] = field(default_factory=list)
    vehicle_types: list[str] = field(default_factory=list)


def _checked(data: Any) -> dict:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected rider RPC response: {data!r}")
    return data


def _pick(cls, data: dict):
    names = cls.__dataclass_fields__.keys()
    return cls(**{k: v for k, v in data.items() if k in names and v is not None})


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def link(tuid: int, tcid: int, phone: str, username: str | None, first_name: str | None) -> RiderLink:
    data = await _rpc(
        "t_rider_link",
        {"p_tuid": tuid, "p_tcid": tcid, "p_phone": phone, "p_username": username, "p_first_name": first_name},
    )
    return _pick(RiderLink, _checked(data))


async def set_profile(tuid: int, town: str | None = None, vehicle_type: str | None = None) -> RiderLink:
    data = await _rpc("t_rider_set_profile", {"p_tuid": tuid, "p_town": town, "p_vehicle_type": vehicle_type})
    return _pick(RiderLink, _checked(data))


async def choices() -> RiderChoices:
    data = await _rpc("t_rider_choices", {})
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected t_rider_choices response: {data!r}")
    return RiderChoices(list(data.get("towns") or []), list(data.get("vehicle_types") or []))


async def profile(tuid: int) -> RiderProfile:
    data = await _rpc("t_rider_profile", {"p_tuid": tuid})
    return _pick(RiderProfile, _checked(data))
