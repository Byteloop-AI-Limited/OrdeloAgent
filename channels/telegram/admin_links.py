"""
Restaurant-admin bot identity: link a Telegram account to an admin record by a verified phone number.
    . Thin async wrapper over SQL functions (RPCs). The rules live in the database, not here (CLAUDE.md, RPC pattern).
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/admin_roster.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        link    -> t_admin_link(p_tuid, p_tcid, p_phone, p_username, p_first_name)   link / move; refuses unknown phones
        profile -> t_admin_profile(p_tuid)                                           who this Telegram account is
    . Table behind them: restaurant_admin (restaurant_admin/admin_roster.sql): tuid authorises, tcid addresses
    . Callers MUST have checked contact.user_id == from_user.id before link(); the phone is never taken from text
    . Called by: channels/telegram/rest_admin/router.py, channels/telegram/rest_admin/channels.py
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
    . Mirrors channels/telegram/rider_links.py (the rider bot's identity wrapper)
  Classes/Functions:
    . AdminRestaurant, AdminLink, AdminProfile
    . link, profile

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_admin_link (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . t_admin_profile (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from config import client_ordelo_service

# t_admin_link results: linked | relinked | already_linked | not_on_roster | tuid_taken | bad_phone
LINKED_RESULTS = frozenset({"linked", "relinked", "already_linked"})


@dataclass(frozen=True)
class AdminRestaurant:
    rest_ref: str
    rest_name: str


@dataclass(frozen=True)
class AdminLink:
    """Outcome of t_admin_link (fields absent from a result stay at their defaults)."""

    result: str
    phone: str | None = None
    channels: tuple[str, ...] = ()
    restaurants: tuple[AdminRestaurant, ...] = ()
    previous_tuid: int | None = None
    previous_username: str | None = None
    phone_last4: str | None = None

    @property
    def is_linked(self) -> bool:
        return self.result in LINKED_RESULTS


@dataclass(frozen=True)
class AdminProfile:
    """Outcome of t_admin_profile."""

    result: str  # ok | not_linked | not_on_roster
    phone: str | None = None
    channels: tuple[str, ...] = ()
    t_first_name: str | None = None
    restaurants: tuple[AdminRestaurant, ...] = ()

    @property
    def is_admin(self) -> bool:
        return self.result == "ok"


def _checked(data: Any) -> dict:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected admin RPC response: {data!r}")
    return data


def _restaurants(data: dict) -> tuple[AdminRestaurant, ...]:
    return tuple(AdminRestaurant(r["rest_ref"], r["rest_name"]) for r in data.get("restaurants") or ())


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def link(tuid: int, tcid: int, phone: str, username: str | None, first_name: str | None) -> AdminLink:
    data = _checked(
        await _rpc(
            "t_admin_link",
            {"p_tuid": tuid, "p_tcid": tcid, "p_phone": phone, "p_username": username, "p_first_name": first_name},
        )
    )
    return AdminLink(
        result=data["result"],
        phone=data.get("phone"),
        channels=tuple(data.get("channels") or ()),
        restaurants=_restaurants(data),
        previous_tuid=data.get("previous_tuid"),
        previous_username=data.get("previous_username"),
        phone_last4=data.get("phone_last4"),
    )


async def profile(tuid: int) -> AdminProfile:
    data = _checked(await _rpc("t_admin_profile", {"p_tuid": tuid}))
    return AdminProfile(
        result=data["result"],
        phone=data.get("phone"),
        channels=tuple(data.get("channels") or ()),
        t_first_name=data.get("t_first_name"),
        restaurants=_restaurants(data),
    )
