"""Issue rider dashboard access for the verified Telegram actor; never accept a rider phone.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . rider_dashboard_mint (function, ordelo_datamodels/admin_dashboard/auth_sessions.sql): calls (service-role only)
(end of database objects)

SQL serializes linkage and issuance. This module owns randomness and the configured frontend URL.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from config import client_ordelo_service
from config.params import get_dashboard_app_url_async


@dataclass(frozen=True)
class DashboardLink:
    result: str  # ok | not_linked
    url: str | None = None


async def issue_link(tuid: int) -> DashboardLink:
    """Return a single-use HTTPS link, authorized atomically by the linked Telegram sender."""
    base = (await get_dashboard_app_url_async("rider")).rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("rider dashboard requires a configured HTTPS origin")
    token = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(token.encode()).hexdigest()
    response = await asyncio.to_thread(
        lambda: client_ordelo_service.rpc("rider_dashboard_mint", {"p_tuid": tuid, "p_token_hash": hashed}).execute()
    )
    data = response.data
    if not isinstance(data, dict) or data.get("result") not in {"ok", "not_linked"}:
        raise RuntimeError("unexpected rider dashboard mint outcome")
    return DashboardLink(data["result"], f"{base}/rider/activate/{token}" if data["result"] == "ok" else None)
