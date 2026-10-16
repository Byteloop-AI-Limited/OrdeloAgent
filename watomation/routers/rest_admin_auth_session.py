"""rest admin auth session.

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
    rest_ref = _resolve_rest_ref(rows.data[0]["rest_ref"])

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
