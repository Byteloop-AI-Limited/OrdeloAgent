import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import client_ordelo, logger

router = APIRouter(prefix="/admin", tags=["admin"])


async def mint_dashboard_session(wa_number: str) -> str:
    # Resolve rest_ref from restaurant_master.admins[]
    rows = await asyncio.to_thread(
        lambda: client_ordelo.table("restaurant_master")
        .select("rest_ref")
        .contains("admins", [wa_number])
        .execute()
    )
    if not rows.data:
        raise ValueError("not_admin")
    rest_ref = rows.data[0]["rest_ref"]

    # Get dashboard base URL from ordelo_config
    cfg = await asyncio.to_thread(
        lambda: client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", "ORDELO_APP_URL")
        .single()
        .execute()
    )
    app_url = cfg.data["config_value"]

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)

    await asyncio.to_thread(
        lambda: client_ordelo.table("dashboard_sessions").insert({
            "admin_id":   wa_number,
            "rest_ref":   rest_ref,
            "wa_number":  wa_number,
            "token_hash": token_hash,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }).execute()
    )

    logger.info(f"Dashboard session minted for {wa_number} rest_ref={rest_ref} expires={expires_at.isoformat()}")
    return f"{app_url}/admin/activate/{token}"



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
        raise HTTPException(status_code=400, detail="admin_binding_mismatch")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    return CreateSessionResponse(url=url, expires_at=expires_at)
