"""Authenticated sys-admin payout endpoints and trusted internal magic-link minting.
    . Mints sessions only through the authenticated WhatsApp helper; no public HTTP mint endpoint
    . require_sys_admin validates the forwarded browser credential and UA, expiry, revocation and overwatch membership
    . Returns the rider payout report by delegating the join to the `get_rider_payout_report`
      Postgres function (see ordelo_datamodels/admin_dashboard/get_rider_payout_report.sql),
      then aggregating per payee in Python
    . Report is location-agnostic: every town / rest_ref with completed dispatches appears,
      and each row carries `town` + `rest_ref` so payouts can be attributed per location
    . Marks `delivery_dispatch` rows as paid (idempotent, only flips rows still `paid_status='unpaid'`)
  Functions/Classes:
    . _sha256_hex
    . _ensure_sys_admin
    . _payee_key
    . fetch_payouts
    . CreateSysAdminSessionResponse
    . UpdatePaidRequest
    . UpdatePaidResponse
    . create_sys_admin_dashboard_session - importable; accepts wa_number directly
    . get_rider_payout
    . update_paid_status
  Key Endpoints:
    . GET  /sys-admin/rider-payout      - payout report for a date range
    . POST /sys-admin/update-paid       - mark dispatch_ids as paid

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . auth_sessions (table, ordelo_datamodels/admin_dashboard/auth_sessions.sql): inserts, named in code (passed to a query helper)
  . ordelo_config (table, ordelo_datamodels/core/ordelo_config.sql): reads the current overwatch authorization allowlist
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): named in code (passed to a query helper), updates
  . get_rider_payout_report (function, ordelo_datamodels/admin_dashboard/get_rider_payout_report.sql): calls (name passed to a helper)
(end of database objects)
"""

import asyncio
import hashlib
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends, Header
from pydantic import BaseModel, Field

from config import client_ordelo, client_ordelo_service, logger
from config.params import get_dashboard_app_url_async

async def require_sys_admin(
    authorization: str | None = Header(default=None),
    x_dashboard_user_agent: str | None = Header(default=None),
):
    """Validate the actual sys-admin browser credential forwarded by the server proxy."""
    if not authorization or not authorization.startswith("Bearer ") or not x_dashboard_user_agent:
        raise HTTPException(status_code=401, detail="sys_admin_session_required")
    cookie = authorization[7:]
    try:
        response = await asyncio.to_thread(lambda: client_ordelo_service.table("auth_sessions")
            .select("id,role,principal_id,revoked,activated_at,hard_expires_at,last_seen_at,bound_ua_hash")
            .eq("cookie_hash", _sha256_hex(cookie)).maybe_single().execute())
    except Exception:
        raise HTTPException(status_code=503, detail="session_store_unavailable") from None
    row = response.data or {}
    now = datetime.now(timezone.utc)
    def timestamp(name):
        try:
            value = datetime.fromisoformat(row[name].replace("Z", "+00:00"))
            return value if value.tzinfo else datetime.min.replace(tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)
    if (row.get("role") != "sys_admin" or row.get("revoked") is not False
        or not row.get("activated_at") or timestamp("hard_expires_at") <= now
        or timestamp("last_seen_at") <= now-timedelta(hours=1)
        or row.get("bound_ua_hash") != _sha256_hex(x_dashboard_user_agent)):
        raise HTTPException(status_code=401, detail="sys_admin_session_required")
    await _ensure_sys_admin(row["principal_id"])


router = APIRouter(prefix="/sys-admin", tags=["sys_admin"], dependencies=[Depends(require_sys_admin)])

LINK_TTL_MINUTES = 30

# Internal test accounts omitted from payouts. Passed to get_rider_payout_report so the
# list can change here without a DB migration.
EXCLUDE_RIDER_IDS = ["447448440754"]

PAYOUT_REPORT_RPC = "get_rider_payout_report"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _ensure_sys_admin(wa_number: str) -> str:
    """Authorize against the current allowlist; the alerts cache is not an authorization cache."""
    principal_id = wa_number.lstrip("+")
    try:
        response = await asyncio.to_thread(lambda: client_ordelo_service.table("ordelo_config")
            .select("config_value").eq("config_key", "overwatch_list").limit(1).execute())
        overwatch = [value.strip() for value in response.data[0]["config_value"].split(",") if value.strip()]
    except Exception:
        raise HTTPException(status_code=503, detail="authorization_store_unavailable") from None
    if principal_id not in overwatch:
        raise HTTPException(status_code=403, detail="sys_admin_not_authorized")
    return principal_id


# ---------------------------------------------------------------------------
# Endpoint 1: dashboard-session
# ---------------------------------------------------------------------------


class CreateSysAdminSessionResponse(BaseModel):
    url: str
    expires_at: datetime


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


def _payee_key(row: dict) -> str:
    """Stable grouping key for a payout row.

    Rows are paid per bank account. Riders with no registration on file have no account to
    group by, so they fall back to their own rider_id - that keeps them visible as an
    individual card instead of merging every unknown rider into one blob.
    """
    account = row.get("bank_account")
    if not account:
        return f"rider:{row['rider_id']}"
    return f"bank:{row.get('bank_account_name')}|{row.get('sort_code')}|{account}"


def fetch_payouts(start_date: str, end_date: str) -> dict:
    """Synchronous payout aggregator.

    Delegates the join to the `get_rider_payout_report` Postgres function (one row per
    completed dispatch in [start_date, end_date], both days inclusive, minus
    EXCLUDE_RIDER_IDS) and aggregates per payee. No town / rest_ref filtering is applied:
    all locations are reported, and each row carries both so payouts can be attributed.
    Returns a JSON-serializable dict with detailed and aggregated rows.
    """
    rows = (
        client_ordelo.rpc(
            PAYOUT_REPORT_RPC,
            {
                "p_start":           start_date,
                "p_end":             end_date,
                "p_exclude_riders":  EXCLUDE_RIDER_IDS,
            },
        )
        .execute()
        .data
    ) or []

    detailed: List[dict] = [
        {
            "payee_key":         _payee_key(row),
            "bank_account_name": row.get("bank_account_name"),
            "sort_code":         row.get("sort_code"),
            "bank_account":      row.get("bank_account"),
            "dispatch_id":       row["dispatch_id"],
            "order_number":      row["order_number"],
            "rest_ref":          row.get("rest_ref"),
            "rider_id":          row["rider_id"],
            "rider_name":        row.get("rider_name"),
            "town":              row.get("town"),
            "vehicle_type":      row.get("vehicle_type"),
            "rider_payout":      row["rider_payout"],
            "dtts":              row["dtts"],
            "paid_status":       row["paid_status"],
            "paid_dtts":         row.get("paid_dtts"),
        }
        for row in rows
    ]

    agg_acc: dict = defaultdict(
        lambda: {"rider_payout": 0.0, "order_count": 0, "rider_names": [], "towns": []}
    )
    for row in detailed:
        acc = agg_acc[row["payee_key"]]
        acc["rider_payout"] += row["rider_payout"]
        acc["order_count"] += 1
        for field, value in (("rider_names", row["rider_name"]), ("towns", row["town"])):
            if value and value not in acc[field]:
                acc[field].append(value)
        acc.setdefault("bank_account_name", row["bank_account_name"])
        acc.setdefault("sort_code", row["sort_code"])
        acc.setdefault("bank_account", row["bank_account"])

    aggregated = [
        {
            "payee_key":            key,
            "bank_account_name":    totals["bank_account_name"],
            "sort_code":            totals["sort_code"],
            "bank_account":         totals["bank_account"],
            "rider_names":          totals["rider_names"],
            "towns":                totals["towns"],
            "rider_payout":         round(totals["rider_payout"], 2),
            "order_count":          totals["order_count"],
            "missing_bank_details": not totals["bank_account"],
        }
        for key, totals in agg_acc.items()
    ]
    aggregated.sort(key=lambda a: a["rider_payout"], reverse=True)

    missing = [a for a in aggregated if a["missing_bank_details"]]
    if missing:
        logger.warning(
            f"[sys_admin.rider_payout] {len(missing)} payee(s) have no bank details on file: "
            f"{[a['rider_names'] or a['payee_key'] for a in missing]}"
        )

    return {
        "start": start_date,
        "end": end_date,
        "total_orders": len(detailed),
        "detailed": detailed,
        "aggregated": aggregated,
    }


@router.get(
    "/rider-payout",
    summary="Rider payout report for a date range",
    description=(
        "Aggregates completed dispatches in `[start, end]` by payee. Both dates are "
        "inclusive of the whole day. Sourced from the `get_rider_payout_report` Postgres "
        "function, which joins `delivery_dispatch -> rider_master -> delivery_summary -> "
        "rider_registrations` and excludes internal test riders. Covers **all** towns and "
        "`rest_ref`s - each detail row carries `town` and `rest_ref` so payouts can be "
        "attributed per location. Riders with no bank details on file are still reported, "
        "grouped under their own `payee_key` with `missing_bank_details=true`. If `end` is "
        "omitted, defaults to `start + 6 days`."
    ),
    response_description="Detailed per-order rows and aggregated per-payee totals",
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
                                "payee_key": "bank:Jane Doe|12-34-56|12345678",
                                "bank_account_name": "Jane Doe",
                                "sort_code": "12-34-56",
                                "bank_account": "12345678",
                                "dispatch_id": 101,
                                "order_number": "BNAT-ABCD-1",
                                "rest_ref": "BNAT",
                                "rider_id": "447700900123",
                                "rider_name": "Jane",
                                "town": "Orpington",
                                "vehicle_type": "scooter",
                                "rider_payout": 4.5,
                                "dtts": "2026-03-28T12:34:56",
                                "paid_status": "unpaid",
                                "paid_dtts": None,
                            }
                        ],
                        "aggregated": [
                            {
                                "payee_key": "bank:Jane Doe|12-34-56|12345678",
                                "bank_account_name": "Jane Doe",
                                "sort_code": "12-34-56",
                                "bank_account": "12345678",
                                "rider_names": ["Jane"],
                                "towns": ["Orpington"],
                                "rider_payout": 4.5,
                                "order_count": 1,
                                "missing_bank_details": False,
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
