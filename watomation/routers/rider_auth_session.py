import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import client_ordelo, logger
from config.params import get_dashboard_app_url_async

router = APIRouter(prefix="/rider", tags=["rider"])

LINK_TTL_MINUTES = 30


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _resolve_rider_id(wa_number: str) -> str:
    """Normalize wa_number to digits-only and verify it exists in rider_master."""
    rider_id = wa_number.lstrip("+")
    rows = await asyncio.to_thread(
        lambda: client_ordelo.table("rider_master")
        .select("rider_id")
        .eq("rider_id", rider_id)
        .execute()
    )
    if not rows.data:
        raise HTTPException(status_code=400, detail="rider_not_registered")
    if len(rows.data) > 1:
        # Data-integrity issue: rider_master has no unique constraint on rider_id.
        # Reject rather than silently pick the wrong rider.
        raise HTTPException(status_code=409, detail="multiple_rider_records")
    return rider_id


class CreateRiderSessionRequest(BaseModel):
    wa_number: str


class CreateRiderSessionResponse(BaseModel):
    url: str
    expires_at: datetime


@router.post("/dashboard-session", response_model=CreateRiderSessionResponse)
async def create_rider_dashboard_session(payload: CreateRiderSessionRequest):
    rider_id = await _resolve_rider_id(payload.wa_number)
    app_url  = await get_dashboard_app_url_async("rider")

    token      = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(token)
    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=LINK_TTL_MINUTES)

    await asyncio.to_thread(
        lambda: client_ordelo.table("auth_sessions").insert({
            "role":         "rider",
            "principal_id": rider_id,
            "scope_ref":    None,
            "wa_number":    rider_id,
            "token_hash":   token_hash,
            "created_at":   now.isoformat(),
            "expires_at":   expires_at.isoformat(),
        }).execute()
    )

    logger.info(
        f"[rider.session.mint] rider_id_hash={_sha256_hex(rider_id)[:8]} "
        f"expires={expires_at.isoformat()}"
    )

    return CreateRiderSessionResponse(
        url=f"{app_url}/rider/activate/{token}",
        expires_at=expires_at,
    )
