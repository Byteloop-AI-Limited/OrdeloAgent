"""rest admin auth session: mints restaurant-admin dashboard magic links into `auth_sessions`.
    . mint_dashboard_session(wa_number)            WhatsApp `/login` and POST /rest-admin/dashboard-session: finds the
                                                   restaurant from restaurant_master.admins (first match), then mints
    . mint_dashboard_session_for(phone, rest_ref)  mints for a restaurant the CALLER has already authorised; used by the
                                                   Telegram restaurant bot `/manage` (channels/telegram/rest_admin/manage.py),
                                                   which takes the phone and restaurants from t_admin_profile
    . The link is single-use and is consumed by a GET on /rest-admin/activate/<token> (restaurant-frontend), so senders
      must not let a link preview fetch it.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . auth_sessions (table, ordelo_datamodels/admin_dashboard/auth_sessions.sql): inserts, named in code (passed to a query helper)
  . restaurant_master (table, ordelo_datamodels/core/restaurant_master.sql): reads, named in code (passed to a query helper)
(end of database objects)
"""
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import client_ordelo, logger
from config.params import get_dashboard_app_url_async, _resolve_rest_ref

router = APIRouter(prefix="/rest-admin", tags=["rest_admin"])


async def mint_dashboard_session(wa_number: str) -> str:
    # Resolve rest_ref from restaurant_master.admins[]
    rows = await asyncio.to_thread(
        lambda: client_ordelo.table("restaurant_master")
        .select("rest_ref")
        .contains("admins", [wa_number])
        .execute()
    )
    if not rows.data:
        raise ValueError("not_rest_admin")
    return await mint_dashboard_session_for(wa_number, rows.data[0]["rest_ref"])


async def mint_dashboard_session_for(wa_number: str, rest_ref: str) -> str:
    """Mint a 30-minute single-use dashboard link for `rest_ref`.

    Does NOT check that `wa_number` is an admin of `rest_ref`: the caller must have authorised it (mint_dashboard_session
    via restaurant_master.admins; the Telegram bot via t_admin_profile, which reads the same admins lists).
    `wa_number` is the digits-only phone (auth_sessions.wa_number / principal_id).
    """
    rest_ref = _resolve_rest_ref(rest_ref)
    app_url = await get_dashboard_app_url_async("rest_admin")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)

    await asyncio.to_thread(
        lambda: client_ordelo.table("auth_sessions").insert({
            "role":         "rest_admin",
            "principal_id": wa_number,
            "scope_ref":    rest_ref,
            "wa_number":    wa_number,
            "token_hash":   token_hash,
            "created_at":   now.isoformat(),
            "expires_at":   expires_at.isoformat(),
        }).execute()
    )

    logger.info(f"[rest_admin.session.mint] wa_number={wa_number} rest_ref={rest_ref} expires={expires_at.isoformat()}")
    return f"{app_url}/rest-admin/activate/{token}"



class CreateSessionRequest(BaseModel):
    wa_number: str


class CreateSessionResponse(BaseModel):
    url: str
    expires_at: datetime


@router.post("/dashboard-session", response_model=CreateSessionResponse)
async def create_dashboard_session(payload: CreateSessionRequest):
    try:
        url = await mint_dashboard_session(payload.wa_number)
    except ValueError:
        raise HTTPException(status_code=400, detail="rest_admin_binding_mismatch")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    return CreateSessionResponse(url=url, expires_at=expires_at)
