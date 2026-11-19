"""
Dashboard magic links for every portal (rider, restaurant admin, sys-admin), for a Telegram or WhatsApp actor.
    . The one module that knows how a dashboard link is made: token, sha256, the service-only mint RPC, the configured HTTPS
      origin and the per-portal activation path. Callers pass WHO is asking (Actor) and WHICH portal; they never see a
      token, a hash, an RPC name or a URL rule (plans/telegram-portal-links-and-dashboard-plan.md, M2).
    . Authority lives in SQL, in the same transaction as the insert. RPCs are DEFINED in
      ordelo_datamodels/admin_dashboard/auth_sessions.sql (keep this list and that file's header in sync):
        access(actor)              -> portal_access(p_tuid, p_phone)                   restaurants + sys_admin flag
        issue("rider", actor)      -> rider_dashboard_mint(p_tuid, p_token_hash)        Telegram actor only
        issue("rest_admin", actor) -> portal_access, then rest_admin_dashboard_mint(p_tuid, p_phone, p_rest_ref, p_token_hash)
                                      once per restaurant (membership re-checked per mint); an alias restaurant
                                      (CHKS -> ELAS) gets no separate link when its canonical restaurant is listed
        issue("sys_admin", actor)  -> sys_admin_dashboard_mint(p_tuid, p_phone, p_token_hash)
    . Actor: exactly one of tuid (Telegram from_user.id, linked by a verified contact share) or wa_phone (WhatsApp wa_id,
      verified by Meta). Never a phone typed by a user.
    . Links are single-use, valid 30 minutes, and open a non-consuming page that POSTs to activate (restaurant-frontend
      lib/dashboard-activation.ts), so link previews cannot use them up.
    . Never log a URL, token or full phone.
    . Called by: channels/telegram/rider/dashboard.py (/my_jobs, /portal), channels/telegram/rest_admin/manage.py (/manage),
      channels/telegram/rest_admin/sysadmin.py (/sysadmin, System dashboard button), watomation/on_message_wa_handler.py
      (WhatsApp /login, /sysadmin)
    . Uses client_ordelo_service (the RPCs are service-role only); Supabase REST is synchronous, so asyncio.to_thread.
  Classes/Functions:
    . Actor, PortalAccess, PortalLink, Issued
    . access, issue

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . portal_access (function, ordelo_datamodels/admin_dashboard/auth_sessions.sql): calls (name passed to a helper)
  . rider_dashboard_mint (function, ordelo_datamodels/admin_dashboard/auth_sessions.sql): calls (name passed to a helper)
  . rest_admin_dashboard_mint (function, ordelo_datamodels/admin_dashboard/auth_sessions.sql): calls (name passed to a helper)
  . sys_admin_dashboard_mint (function, ordelo_datamodels/admin_dashboard/auth_sessions.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from config import client_ordelo_service
from config.params import _resolve_rest_ref, get_dashboard_app_url_async

Portal = Literal["rider", "rest_admin", "sys_admin"]

_PATHS: dict[str, str] = {"rider": "/rider/activate/", "rest_admin": "/rest-admin/activate/", "sys_admin": "/sys-admin/activate/"}
_MINT_RESULTS = frozenset({"ok", "not_linked", "not_allowed"})


@dataclass(frozen=True)
class Actor:
    """Who is asking. Exactly one field is set."""

    tuid: int | None = None
    wa_phone: str | None = None

    def __post_init__(self):
        if (self.tuid is None) == (self.wa_phone is None):
            raise ValueError("Actor needs exactly one of tuid and wa_phone")


@dataclass(frozen=True)
class PortalRestaurant:
    rest_ref: str
    rest_name: str


@dataclass(frozen=True)
class PortalAccess:
    """What the actor may open. result: ok | not_linked."""

    result: str
    restaurants: tuple[PortalRestaurant, ...] = ()
    sys_admin: bool = False

    @property
    def can_open_anything(self) -> bool:
        return self.result == "ok" and (bool(self.restaurants) or self.sys_admin)


@dataclass(frozen=True)
class PortalLink:
    label: str
    url: str
    rest_ref: str | None = None


@dataclass(frozen=True)
class Issued:
    """result: ok (links non-empty) | not_linked | not_allowed."""

    result: str
    links: tuple[PortalLink, ...] = ()

    @property
    def ok(self) -> bool:
        return self.result == "ok" and bool(self.links)


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


def _actor_args(actor: Actor) -> dict:
    return {"p_tuid": actor.tuid, "p_phone": actor.wa_phone}


async def _origin(portal: Portal) -> str:
    base = (await get_dashboard_app_url_async(portal)).rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError(f"{portal} dashboard requires a configured HTTPS origin")
    return base


def _token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def _checked(data: Any) -> str:
    if not isinstance(data, dict) or data.get("result") not in _MINT_RESULTS:
        raise RuntimeError("unexpected dashboard mint outcome")
    return data["result"]


async def access(actor: Actor) -> PortalAccess:
    data = await _rpc("portal_access", _actor_args(actor))
    if not isinstance(data, dict) or data.get("result") not in {"ok", "not_linked"}:
        raise RuntimeError("unexpected portal_access outcome")
    return PortalAccess(
        result=data["result"],
        restaurants=tuple(PortalRestaurant(r["rest_ref"], r["rest_name"]) for r in data.get("restaurants") or ()),
        sys_admin=bool(data.get("sys_admin")),
    )


async def issue(portal: Portal, actor: Actor) -> Issued:
    """Mint the portal's link(s) for this actor. Raises only when the store or the configured origin is unavailable."""
    base = await _origin(portal)
    if portal == "rider":
        if actor.tuid is None:
            return Issued("not_allowed")  # rider links are issued to the linked Telegram account only
        token, hashed = _token()
        result = _checked(await _rpc("rider_dashboard_mint", {"p_tuid": actor.tuid, "p_token_hash": hashed}))
        return Issued(result, (PortalLink("Open my jobs", base + _PATHS[portal] + token),) if result == "ok" else ())
    if portal == "sys_admin":
        token, hashed = _token()
        result = _checked(await _rpc("sys_admin_dashboard_mint", {**_actor_args(actor), "p_token_hash": hashed}))
        return Issued(result, (PortalLink("Open system dashboard", base + _PATHS[portal] + token),) if result == "ok" else ())
    if portal != "rest_admin":
        raise ValueError(f"unknown portal {portal!r}")
    acc = await access(actor)
    if acc.result != "ok":
        return Issued("not_linked")
    links = []
    mine = {r.rest_ref for r in acc.restaurants}
    for r in acc.restaurants:
        # An alias restaurant (config.params _REST_REF_ALIAS_MAP, e.g. CHKS -> ELAS) shares its canonical restaurant's
        # orders and settings; when the person admins the canonical one too, its link already covers the alias.
        if _resolve_rest_ref(r.rest_ref) != r.rest_ref and _resolve_rest_ref(r.rest_ref) in mine:
            continue
        token, hashed = _token()
        result = _checked(await _rpc("rest_admin_dashboard_mint",
                                     {**_actor_args(actor), "p_rest_ref": r.rest_ref, "p_token_hash": hashed}))
        if result == "ok":  # not_allowed: removed from this list between access() and the mint; skip it
            links.append(PortalLink(f"Manage {r.rest_name}", base + _PATHS[portal] + token, r.rest_ref))
    return Issued("ok", tuple(links)) if links else Issued("not_allowed")
