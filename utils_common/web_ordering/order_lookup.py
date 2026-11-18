"""Find recent web orders and prove delivery house keys without exposing handover codes.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . web_order_lookup (fn, ordelo_datamodels/ordering/web_order_lookup.sql): reads (SQL)
  . web_order_unlock (fn, ordelo_datamodels/ordering/web_order_lookup.sql): writes (SQL)
  . web_rate_limit (table, ordelo_datamodels/ordering/web_rate_limit.sql): writes (SQL)
  . order_access_grant (table, ordelo_datamodels/ordering/order_access_grant.sql): writes via order_access
(end of database objects)
"""

import hashlib
import secrets
from datetime import timedelta
from loguru import logger
from . import customer_order_view, order_access
from .common import RESTAURANTS, WebError, iso, normalise_postcode, one, query

LOOKUP_DAYS, LOOKUP_LIMIT = 7, 10
STATUS_ONLY_TTL = timedelta(hours=1)
LIMITS = {"find_visitor": 10, "find_postcode": 20, "unlock_visitor": 10, "unlock_order": 5}


async def _hit(kind: str, identity: str) -> None:
    """Count an hourly attempt under a one-way, purpose-separated identity."""
    hashed = hashlib.sha256(f"lookup:{kind}:{identity}".encode()).hexdigest()
    rows = await query(
        """INSERT INTO web_rate_limit(identity_hash,window_start) VALUES (%s,date_trunc('hour',now()))
        ON CONFLICT(identity_hash,window_start) DO UPDATE SET attempts=web_rate_limit.attempts+1 RETURNING attempts""",
        (hashed,),
    )
    if rows[0]["attempts"] > LIMITS[kind]:
        raise WebError("rate_limited", 429)


async def find(postcode: str, rest_ref: str, visitor_hash: str) -> dict:
    """Return a limited status-only list, with one short-lived grant per result."""
    postcode = normalise_postcode(postcode)
    if not postcode:
        raise WebError("invalid_postcode", 400)
    rest_ref = rest_ref.upper()
    if rest_ref not in RESTAURANTS:
        raise WebError("invalid_request", 400)
    await _hit("find_visitor", visitor_hash)
    await _hit("find_postcode", postcode)
    result = await one("SELECT public.web_order_lookup(%s,%s,%s,%s) AS orders",
                       (postcode, rest_ref, LOOKUP_DAYS, LOOKUP_LIMIT))
    rows = result["orders"]
    tokens = await order_access.issue_status_only([r["order_number"] for r in rows], STATUS_ONLY_TTL)
    orders = []
    for row in rows:
        n = row["order_number"]
        view = await customer_order_view.get_view(n, "status_only")
        orders.append({**row, "token": tokens[n], "page_path": view["page_path"],
                       "display_status": view["display_status"],
                       **{k: view[k] for k in ("cancel_reason", "pickup_time") if k in view}})
    logger.info("web order lookup district={} rest_ref={} count={}", postcode.split()[0], rest_ref, len(orders))
    return {"orders": orders}


async def unlock(order_number: str, postcode: str, house: str, visitor_hash: str) -> dict:
    """Atomically prove a house key and mint a recovered grant; all mismatches are 404."""
    postcode = normalise_postcode(postcode)
    if not postcode or order_number.split("-")[0] not in RESTAURANTS:
        raise WebError("not_found", 404)
    await _hit("unlock_visitor", visitor_hash)
    await _hit("unlock_order", order_number)
    token = secrets.token_urlsafe(32)
    result = await one("SELECT public.web_order_unlock(%s,%s,%s,%s,%s) AS outcome",
                       (order_number, postcode, house[:60], order_access.digest(token), LOOKUP_DAYS))
    outcome = result["outcome"]
    logger.info("web order unlock result={}", outcome["result"])
    if outcome["result"] != "ok":
        raise WebError("not_found", 404)
    town = RESTAURANTS[order_number.split("-")[0]]["town"]
    return {"token": token, "expires_at": iso(outcome["expires_at"]),
            "page_path": f"/town/{town}/orders/{order_number}"}
