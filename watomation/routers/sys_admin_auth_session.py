"""Sys-admin scoped HTTP endpoints (auth session, rider payout, paid status).
    . Mints sys_admin dashboard magic-link sessions into `auth_sessions`
    . Gates sys_admin access via `config.params.get_overwatch_list()` allowlist
    . Returns weekly rider payout report joining delivery_dispatch / rider_master / rider_registrations / delivery_option
    . Marks `delivery_dispatch` rows as paid (idempotent, only flips rows still `paid_status='unpaid'`)
  Functions/Classes:
    . _sha256_hex
    . _ensure_sys_admin
    . fetch_payouts
    . CreateSysAdminSessionResponse
    . UpdatePaidRequest
    . UpdatePaidResponse
    . create_sys_admin_dashboard_session - importable; accepts wa_number directly
    . get_rider_payout
    . update_paid_status
  Key Endpoints:
    . POST /sys-admin/dashboard-session - mint sys_admin session
    . GET  /sys-admin/rider-payout      - weekly payout report
    . POST /sys-admin/update-paid       - mark dispatch_ids as paid
"""

import asyncio
import hashlib
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import client_ordelo, logger
from config.params import get_overwatch_list, get_dashboard_app_url_async

router = APIRouter(prefix="/sys-admin", tags=["sys_admin"])

LINK_TTL_MINUTES = 30
EXCLUDE_RIDER_ID = "447448440754"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _ensure_sys_admin(wa_number: str) -> str:
    """Normalize wa_number to digits-only and verify it is in the overwatch list."""
    principal_id = wa_number.lstrip("+")
    overwatch = await asyncio.to_thread(get_overwatch_list)
    if principal_id not in overwatch:
        raise HTTPException(status_code=403, detail="sys_admin_not_authorized")
    return principal_id


# ---------------------------------------------------------------------------
# Endpoint 1: dashboard-session
# ---------------------------------------------------------------------------


class CreateSysAdminSessionResponse(BaseModel):
    url: str
    expires_at: datetime


@router.post(
    "/dashboard-session",
    response_model=CreateSysAdminSessionResponse,
    summary="Mint sys_admin dashboard magic link",
    description=(
        "Issues a 30-minute single-use magic link for the sys_admin dashboard. "
        "`wa_number` is supplied as a query string parameter so the same coroutine "
        "can be imported and called directly from non-HTTP contexts (e.g. WhatsApp "
        "`/sysadmin` command handler). The wa_number must be in the overwatch list "
        "(`ordelo_config.overwatch_list`); otherwise returns 403 `sys_admin_not_authorized`."
    ),
    response_description="Activation URL and absolute expiry timestamp",
    responses={
        200: {
            "description": "Session minted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "url": "https://app.ordelo.example/sys-admin/activate/<token>",
                        "expires_at": "2026-05-21T10:30:00+00:00",
                    }
                }
            },
        },
        403: {"description": "wa_number not in sys_admin allowlist"},
    },
)
async def create_sys_admin_dashboard_session(wa_number: str) -> CreateSysAdminSessionResponse:
    principal_id = await _ensure_sys_admin(wa_number)
    app_url = await get_dashboard_app_url_async("sys_admin")

    token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(token)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=LINK_TTL_MINUTES)

    await asyncio.to_thread(
        lambda: client_ordelo.table("auth_sessions").insert({
            "role":         "sys_admin",
            "principal_id": principal_id,
            "scope_ref":    None,
            "wa_number":    principal_id,
            "token_hash":   token_hash,
            "created_at":   now.isoformat(),
            "expires_at":   expires_at.isoformat(),
        }).execute()
    )

    logger.info(
        f"[sys_admin.session.mint] principal_hash={_sha256_hex(principal_id)[:8]} "
        f"expires={expires_at.isoformat()}"
    )

    return CreateSysAdminSessionResponse(
        url=f"{app_url}/sys-admin/activate/{token}",
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Endpoint 2: rider-payout
# ---------------------------------------------------------------------------


def fetch_payouts(start_date: str, end_date: str) -> dict:
    """Synchronous payout aggregator.

    Joins delivery_dispatch -> rider_master -> rider_registrations -> delivery_option,
    excluding EXCLUDE_RIDER_ID, filtering to completed dispatches within [start, end].
    Returns a JSON-serializable dict with detailed and aggregated rows.
    """
    dispatches = (
        client_ordelo.table("delivery_dispatch")
        .select("dispatch_id, order_number, rider_id, rider_payout, dtts, paid_status")
        .eq("status", "completed")
        .neq("rider_id", EXCLUDE_RIDER_ID)
        .gte("dtts", start_date)
        .lte("dtts", end_date)
        .order("dtts", desc=True)
        .execute()
        .data
    ) or []

    if not dispatches:
        return {
            "start": start_date,
            "end": end_date,
            "total_orders": 0,
            "detailed": [],
            "aggregated": [],
        }

    rider_ids = list({d["rider_id"] for d in dispatches})
    order_numbers = [d["order_number"] for d in dispatches]

    riders = {
        r["rider_id"]: r
        for r in (
            client_ordelo.table("rider_master")
            .select("rider_id, rider_name, vehicle_type")
            .in_("rider_id", rider_ids)
            .execute()
            .data
            or []
        )
    }

    reg_rows = (
        client_ordelo.table("rider_registrations")
        .select("phone, bank_account_name, sort_code, bank_account")
        .execute()
        .data
        or []
    )
    reg_by_rider = {r["phone"][1:]: r for r in reg_rows}

    options = {
        o["order_number"]: o
        for o in (
            client_ordelo.table("delivery_option")
            .select("order_number, vehicle_type")
            .in_("order_number", order_numbers)
            .execute()
            .data
            or []
        )
    }

    detailed: List[dict] = []
    for d in dispatches:
        rider = riders.get(d["rider_id"])
        if not rider:
            continue
        opt = options.get(d["order_number"])
        if not opt or opt["vehicle_type"] != rider["vehicle_type"]:
            continue
        reg = reg_by_rider.get(d["rider_id"])
        if not reg:
            continue
        detailed.append({
            "bank_account_name": reg["bank_account_name"],
            "sort_code":         reg["sort_code"],
            "bank_account":      reg["bank_account"],
            "dispatch_id":       d["dispatch_id"],
            "order_number":      d["order_number"],
            "rider_payout":      d["rider_payout"],
            "dtts":              d["dtts"],
            "paid_status":       d["paid_status"],
        })

    agg_acc: dict = defaultdict(lambda: {"rider_payout": 0.0, "order_count": 0})
    for row in detailed:
        key = (row["bank_account_name"], row["sort_code"], row["bank_account"])
        agg_acc[key]["rider_payout"] += row["rider_payout"]
        agg_acc[key]["order_count"] += 1

    aggregated = [
        {
            "bank_account_name": name,
            "sort_code":         sort,
            "bank_account":      acct,
            "rider_payout":      round(totals["rider_payout"], 2),
            "order_count":       totals["order_count"],
        }
        for (name, sort, acct), totals in agg_acc.items()
    ]

    return {
        "start": start_date,
        "end": end_date,
        "total_orders": len(detailed),
        "detailed": detailed,
        "aggregated": aggregated,
    }


@router.get(
    "/rider-payout",
    summary="Weekly rider payout report",
    description=(
        "Aggregates completed dispatches in `[start, end]` (inclusive) by rider bank "
        "account. Joins `delivery_dispatch -> rider_master -> rider_registrations -> "
        "delivery_option` and excludes internal test rider. If `end` is omitted, "
        "defaults to `start + 6 days`."
    ),
    response_description="Detailed per-order rows and aggregated per-rider totals",
    responses={
        200: {
            "description": "Payout report (empty arrays if no matching dispatches)",
            "content": {
                "application/json": {
                    "example": {
                        "start": "2026-03-27",
                        "end": "2026-04-02",
                        "total_orders": 1,
                        "detailed": [
                            {
                                "bank_account_name": "Jane Doe",
                                "sort_code": "12-34-56",
                                "bank_account": "12345678",
                                "dispatch_id": 101,
                                "order_number": "ELAS-ABCD-1",
                                "rider_payout": 4.5,
                                "dtts": "2026-03-28T12:34:56",
                                "paid_status": "unpaid",
                            }
                        ],
                        "aggregated": [
                            {
                                "bank_account_name": "Jane Doe",
                                "sort_code": "12-34-56",
                                "bank_account": "12345678",
                                "rider_payout": 4.5,
                                "order_count": 1,
                            }
                        ],
                    }
                }
            },
        },
        400: {"description": "Invalid `start`/`end` date or `end < start`"},
    },
)
async def get_rider_payout(
    start: str = Query(..., description="Start date inclusive, ISO YYYY-MM-DD (typically a Friday)"),
    end: Optional[str] = Query(None, description="End date inclusive, ISO YYYY-MM-DD. Defaults to start+6 days."),
):
    try:
        start_d = date.fromisoformat(start)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_start_date")

    if end is None:
        end_d = start_d + timedelta(days=6)
    else:
        try:
            end_d = date.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_end_date")

    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end_before_start")

    report = await asyncio.to_thread(fetch_payouts, start_d.isoformat(), end_d.isoformat())
    return report


# ---------------------------------------------------------------------------
# Endpoint 3: update-paid
# ---------------------------------------------------------------------------


class UpdatePaidRequest(BaseModel):
    dispatch_ids: List[int] = Field(..., min_length=1)


class UpdatePaidResponse(BaseModel):
    updated_count: int
    dispatch_ids_updated: List[int]
    dispatch_ids_skipped: List[int]


@router.post(
    "/update-paid",
    response_model=UpdatePaidResponse,
    summary="Mark dispatch_ids as paid",
    description=(
        "Idempotently flips `delivery_dispatch.paid_status` from `unpaid` to `paid` "
        "and stamps `paid_dtts=now()` for the supplied `dispatch_ids`. Rows already "
        "`paid` are skipped (returned in `dispatch_ids_skipped`), so retries are safe."
    ),
    response_description="Counts and ids of rows actually updated vs skipped",
    responses={
        200: {
            "description": "Update completed",
            "content": {
                "application/json": {
                    "example": {
                        "updated_count": 2,
                        "dispatch_ids_updated": [101, 102],
                        "dispatch_ids_skipped": [103],
                    }
                }
            },
        },
        422: {"description": "`dispatch_ids` missing, empty, or contains non-positive ints"},
    },
)
async def update_paid_status(payload: UpdatePaidRequest):
    if any(d <= 0 for d in payload.dispatch_ids):
        raise HTTPException(status_code=422, detail="dispatch_ids_must_be_positive")

    now_iso = datetime.now(timezone.utc).isoformat()

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("delivery_dispatch")
        .update({"paid_status": "paid", "paid_dtts": now_iso})
        .in_("dispatch_id", payload.dispatch_ids)
        .eq("paid_status", "unpaid")
        .execute()
    )

    updated_rows = resp.data or []
    updated_ids = [row["dispatch_id"] for row in updated_rows]
    skipped_ids = [d for d in payload.dispatch_ids if d not in set(updated_ids)]

    logger.info(
        f"[sys_admin.update_paid] requested={len(payload.dispatch_ids)} "
        f"updated={len(updated_ids)} skipped={len(skipped_ids)}"
    )

    return UpdatePaidResponse(
        updated_count=len(updated_ids),
        dispatch_ids_updated=updated_ids,
        dispatch_ids_skipped=skipped_ids,
    )
