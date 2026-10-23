"""
Restaurant admins pause and resume their Telegram order alerts (phase R6; ADR 0013, D51, D52).
    . Thin typed wrapper over the t_admin_pause* RPCs (CLAUDE.md, RPC pattern). The rules live in SQL: which restaurants a
      Telegram user is an admin of (claimed invite + phone in restaurant_master.admins, D14), the durations policy and the
      last-admin guard (pause_start in availability/pauses.sql).
    . RPCs are DEFINED in: ordelo_datamodels/telegram/t_admin_pauses.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        pause   -> t_admin_pause(p_bot_key, p_tuid, p_duration)
        resume  -> t_admin_resume(p_bot_key, p_tuid)
        status  -> t_admin_pause_status(p_bot_key, p_tuid)
        chats   -> t_admin_pause_chats(p_bot_key, p_phone, p_rest_ref)
    . Callers: channels/telegram/rest_admin/pauses.py (/off, /on and the duration taps); watomation/routers/pause_hooks.py
      (chats: where an admin's "ends soon" / "back on" goes)
    . Uses client_ordelo_service (service-role only RPCs) inside asyncio.to_thread
  Classes/Functions:
    . RestaurantPause, AdminPauseOutcome
    . pause, resume, status, chats

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . t_admin_pause (function, ordelo_datamodels/telegram/t_admin_pauses.sql): calls (name passed to a helper)
  . t_admin_resume (function, ordelo_datamodels/telegram/t_admin_pauses.sql): calls (name passed to a helper)
  . t_admin_pause_status (function, ordelo_datamodels/telegram/t_admin_pauses.sql): calls (name passed to a helper)
  . t_admin_pause_chats (function, ordelo_datamodels/telegram/t_admin_pauses.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import client_ordelo_service


@dataclass(frozen=True)
class RestaurantPause:
    rest_ref: str
    rest_name: str
    result: str | None = None  # pause: paused | extended | bad_duration | not_admin | not_allowed ; resume: resumed | not_paused
    paused: bool | None = None  # status only
    ends_at: datetime | None = None


@dataclass(frozen=True)
class AdminPauseOutcome:
    result: str  # ok | not_linked
    restaurants: tuple[RestaurantPause, ...] = ()
    options: tuple[str, ...] = field(default=())  # status only: the /off durations

    @property
    def is_linked(self) -> bool:
        return self.result == "ok"


def _ts(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _outcome(data: Any) -> AdminPauseOutcome:
    if not isinstance(data, dict) or data.get("result") not in ("ok", "not_linked"):
        raise RuntimeError(f"unexpected admin pause RPC response: {data!r}")
    rows = tuple(
        RestaurantPause(r["rest_ref"], r.get("rest_name") or r["rest_ref"], r.get("result"), r.get("paused"),
                        _ts(r.get("ends_at")))
        for r in data.get("restaurants") or ()
    )
    return AdminPauseOutcome(data["result"], rows, tuple(data.get("options") or ()))


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def pause(bot_key: str, tuid: int, duration: str) -> AdminPauseOutcome:
    """Pause this person's alerts for every restaurant they are a linked admin of (one result per restaurant)."""
    return _outcome(await _rpc("t_admin_pause", {"p_bot_key": bot_key, "p_tuid": tuid, "p_duration": duration}))


async def resume(bot_key: str, tuid: int) -> AdminPauseOutcome:
    """End this person's alert pauses now, for every restaurant they are a linked admin of."""
    return _outcome(await _rpc("t_admin_resume", {"p_bot_key": bot_key, "p_tuid": tuid}))


async def status(bot_key: str, tuid: int) -> AdminPauseOutcome:
    """Per restaurant: paused or not and until when; plus the durations /off may offer."""
    return _outcome(await _rpc("t_admin_pause_status", {"p_bot_key": bot_key, "p_tuid": tuid}))


async def chats(bot_key: str, phone: str, rest_ref: str) -> list[tuple[int, str]]:
    """The admin's Telegram chats for that restaurant as (tcid, rest_name); [] when they have none."""
    data = await _rpc("t_admin_pause_chats", {"p_bot_key": bot_key, "p_phone": phone, "p_rest_ref": rest_ref})
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected t_admin_pause_chats response: {data!r}")
    return [(int(r["tcid"]), r.get("rest_name") or rest_ref) for r in data]
