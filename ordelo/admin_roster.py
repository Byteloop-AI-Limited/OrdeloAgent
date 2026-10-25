"""
Admin roster: who a restaurant's admins are and where each one hears from Ordelo (CONTEXT.md: Admin roster, Admin channels).
    . Thin async wrapper over SQL functions (RPCs). The rules live in the database, not here (CLAUDE.md, RPC pattern).
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/admin_roster.sql
      (keep this list and that file's header in sync whenever either changes)
    . Python function -> RPC it calls:
        recipients      -> admin_recipients(p_rest_ref, p_channel)
        whatsapp_phones -> admin_recipients(p_rest_ref, 'whatsapp'); FAILS OPEN to today's restaurant_master.admins list
        set_channels    -> admin_set_channels(p_phone, p_channels, p_by)
        unlink_telegram -> admin_unlink_telegram(p_phone, p_by)
        roster_status   -> admin_roster_status(p_rest_ref)
    . Called by: channels/telegram/rest_admin/channels.py (/channels), channels/telegram/admin_links.py users; from phase P2
      utils_common/notify/restaurant_notifier.py (the WhatsApp adapter) and watomation/routers/delivery_hooks.py
    . Uses client_ordelo_service: the RPCs are service-role only (anon is denied)
    . Supabase REST is synchronous, so every call runs in asyncio.to_thread (CLAUDE.md rule)
  Classes/Functions:
    . Recipient, ChannelsOutcome
    . recipients, whatsapp_phones, set_channels, unlink_telegram, roster_status

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . admin_recipients (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_set_channels (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_unlink_telegram (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_roster_status (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from config import client_ordelo_service, logger

Channel = Literal["whatsapp", "telegram"]
SET_CHANNELS_RESULTS = frozenset({"ok", "not_found", "bad_channels", "not_linked"})


@dataclass(frozen=True)
class Recipient:
    """One admin who gets a NEW message on a channel (admin_recipients row)."""

    phone: str
    tcid: int | None
    tuid: int | None
    label: str | None


@dataclass(frozen=True)
class ChannelsOutcome:
    """Outcome of admin_set_channels / admin_unlink_telegram."""

    result: str
    channels: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.result == "ok"


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


def _outcome(data: Any) -> ChannelsOutcome:
    if not isinstance(data, dict) or "result" not in data:
        raise RuntimeError(f"unexpected admin roster response: {data!r}")
    return ChannelsOutcome(data["result"], tuple(data.get("channels") or ()))


async def recipients(rest_ref: str, channel: Channel) -> list[Recipient]:
    data = await _rpc("admin_recipients", {"p_rest_ref": rest_ref, "p_channel": channel})
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected admin_recipients response: {data!r}")
    return [Recipient(r["phone"], r.get("tcid"), r.get("tuid"), r.get("label")) for r in data]


async def _todays_admins(rest_ref: str | None, fallback: Iterable[str] | None) -> list[str]:
    if fallback is None and rest_ref:
        from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

        fallback = await asyncio.to_thread(RestaurantMaster.get_admins_for, rest_ref) or []
    return list(dict.fromkeys(a for a in (fallback or []) if a))


async def whatsapp_phones(rest_ref: str | None, *, fallback: Iterable[str] | None = None) -> list[str]:
    """The admins of rest_ref who get WhatsApp now (list order). NEVER raises and never returns fewer people than today
    because of a fault: with no rest_ref or on any RPC failure it returns `fallback` (or, when None,
    restaurant_master.admins), deduped in order: exactly today's behaviour."""
    if rest_ref:
        try:
            return [r.phone for r in await recipients(rest_ref, "whatsapp")]
        except Exception:
            logger.exception(f"admin_roster: whatsapp recipients for {rest_ref} failed; using restaurant_master.admins")
    return await _todays_admins(rest_ref, fallback)


async def set_channels(phone: str, channels: Iterable[str], by: str) -> ChannelsOutcome:
    data = await _rpc("admin_set_channels", {"p_phone": phone, "p_channels": list(channels), "p_by": by})
    return _outcome(data)


async def unlink_telegram(phone: str, by: str) -> ChannelsOutcome:
    data = await _rpc("admin_unlink_telegram", {"p_phone": phone, "p_by": by})
    return _outcome(data)


async def roster_status(rest_ref: str) -> list[dict]:
    data = await _rpc("admin_roster_status", {"p_rest_ref": rest_ref})
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected admin_roster_status response: {data!r}")
    return data
