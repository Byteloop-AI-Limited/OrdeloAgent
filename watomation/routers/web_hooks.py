"""Authenticated R3 web checkout and token-protected, read-only status API.

Browser requests arrive through Next.js. Secrets and customer IDs never enter
browser bodies. Each order status/token operation checks its grant separately.
"""

import hashlib
import os
import re
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from aws_setting import agent_env
from utils_common.web_ordering import (
    availability,
    order_access,
    web_checkout,
    customer_order_view,
)
from utils_common.web_ordering.common import WebError, query, RESTAURANTS


async def require_key(request: Request):
    expected = os.environ.get("ORDELO_WEB_KEY") or agent_env.get("ordelo_web_key", "")
    supplied = request.headers.get("X-Ordelo-Web-Key", "")
    if len(expected) < 32:
        raise WebError("web_unavailable", 503)
    if not secrets.compare_digest(supplied, expected):
        raise WebError("unauthorised", 401)


router = APIRouter(tags=["web"], dependencies=[Depends(require_key)])
PRIVATE = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}


class Eligibility(BaseModel):
    postcode: str = Field(min_length=5, max_length=10)
    mode: Literal["delivery", "collection"] = "delivery"
    rest_refs: list[str] = Field(max_length=20)


@router.post("/eligibility")
async def eligibility(body: Eligibility):
    postcode = body.postcode.strip().upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}", postcode):
        raise WebError("invalid_postcode", 400)
    postcode = postcode[:-3] + " " + postcode[-3:]
    refs = [ref.upper() for ref in body.rest_refs if ref.upper() in RESTAURANTS]
    return JSONResponse(
        await availability.eligibility(postcode, body.mode, refs), headers=PRIVATE
    )


class Session(BaseModel):
    rest_ref: str = Field(min_length=4, max_length=4)
    mode: Literal["delivery", "collection"]
    town_slug: str = Field(max_length=80)
    visitor_id: str = Field(min_length=1, max_length=80)
    postcode_district: str | None = Field(default=None, max_length=5)
    postcode: str | None = Field(default=None, max_length=10)


@router.post("/checkout-sessions", status_code=201)
async def start(body: Session, request: Request):
    # Next derives this opaque hash from the network peer and its server secret.
    identity = request.headers.get("X-Ordelo-Visitor-Hash", "")
    if not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise WebError("invalid_request", 400)
    rows = await query(
        """INSERT INTO web_rate_limit(identity_hash,window_start) VALUES (%s,date_trunc('hour',now()))
        ON CONFLICT(identity_hash,window_start) DO UPDATE SET attempts=web_rate_limit.attempts+1 RETURNING attempts""",
        (identity,),
    )
    if rows[0]["attempts"] > 20:
        raise WebError("rate_limited", 429)
    return JSONResponse(
        await web_checkout.start(
            body.rest_ref.upper(),
            body.mode,
            body.town_slug,
            body.visitor_id,
            body.postcode_district,
            postcode=body.postcode,
        ),
        201,
        headers=PRIVATE,
    )


class Address(BaseModel):
    thread_id: str = Field(max_length=150)
    cust_id: str = Field(max_length=30)
    address: dict


class ResumeSession(BaseModel):
    thread_id: str = Field(min_length=1, max_length=150)
    cust_id: str = Field(min_length=1, max_length=30)


@router.post("/checkout-sessions/resume")
async def resume(body: ResumeSession):
    current = await web_checkout.session(body.thread_id, body.cust_id)
    await availability.available(current["rest_ref"], current["mode"])
    return JSONResponse({"ok": True}, headers=PRIVATE)


@router.post("/address")
async def address(body: Address):
    if len(str(body.address)) > 2000:
        raise WebError("invalid_address")
    return JSONResponse(
        await web_checkout.address(body.thread_id, body.cust_id, body.address),
        headers=PRIVATE,
    )


@router.post("/orders", status_code=201)
async def create(
    body: web_checkout.OrderInput,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", idempotency_key):
        raise WebError("invalid_request", 400)
    return JSONResponse(
        await web_checkout.create(body, idempotency_key), 201, headers=PRIVATE
    )


@router.get("/orders/{order_number}")
async def view(order_number: str, request: Request):
    grant = await order_access.verify(
        request.headers.get("X-Order-Access", ""), order_number
    )
    result = await customer_order_view.get_view(order_number, grant["detail_level"])
    etag = '"' + hashlib.sha256(str(result).encode()).hexdigest() + '"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=PRIVATE | {"ETag": etag})
    return JSONResponse(result, headers=PRIVATE | {"ETag": etag})


@router.post("/access/exchange")
async def exchange(request: Request):
    # Raw secret arrives in a header; never a path/query/access log.
    grant = await order_access.verify(request.headers.get("X-Order-Access", ""))
    ref = grant["order_number"].split("-")[0]
    return JSONResponse(
        {
            "order_number": grant["order_number"],
            "page_path": f"/town/{RESTAURANTS[ref]['town']}/orders/{grant['order_number']}",
        },
        headers=PRIVATE,
    )


class CollectionEligibility(BaseModel):
    rest_refs: list[str] = Field(max_length=20)


@router.post("/availability")
async def collection_availability(body: CollectionEligibility):
    refs = [ref.upper() for ref in body.rest_refs if ref.upper() in RESTAURANTS]
    return JSONResponse(
        await availability.eligibility("", "collection", refs), headers=PRIVATE
    )
