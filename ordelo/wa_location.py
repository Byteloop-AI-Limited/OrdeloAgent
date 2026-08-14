"""Durable on-demand WhatsApp location orchestration.

This module owns the delivery-authority checks, request/observation persistence,
prompt coalescing, correlation, and response routing.  HTTP and PyWa adapters
remain deliberately thin and must not duplicate these decisions.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from psycopg.rows import dict_row

from config import logger, pg_settings
from ordelo_datamodels.wa_location_pymodels import (
    RestaurantConfirmationObservation,
    WaLocationCallbackPayload,
    WaLocationDemand,
    WaLocationRequestOutcome,
    WhatsAppLocationReceipt,
)

FRESHNESS = timedelta(minutes=5)
PROMPT_COOLDOWN = timedelta(minutes=5)


class WaLocationError(Exception):
    """Base class for deterministic WaLocation failures."""


class WaLocationNotFound(WaLocationError):
    code = "active_dispatch_not_found"

    def __init__(self) -> None:
        super().__init__(self.code)


class WaLocationForbidden(WaLocationError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WaLocationConflict(WaLocationError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WaLocationCallbackDeliveryFailed(WaLocationError):
    code = "callback_delivery_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class _DeliveryContext:
    order_number: str
    customer_id: str
    dispatch_id: int
    rider_id: str
    dispatch_status: str
    admins: list[str]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WaLocation:
    """Ordelo-owned durable implementation of the WaLocation public interface."""

    def __init__(self, *, wa_client: Any) -> None:
        self._wa_client = wa_client

    async def request(self, demand: WaLocationDemand) -> WaLocationRequestOutcome:
        """Validate demand, persist it, route fresh data, or prompt one rider."""

        self._validate_rest_ref(demand)
        await self._validate_public_callback_url(demand.callback_url)
        pool = await pg_settings.get_pool()
        decision: tuple[str, UUID, _DeliveryContext, str | None] | None = None

        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (demand.order_number,),
                    )
                    context = await self._load_delivery_context(cur, demand.order_number)
                    await self._validate_demand(cur, demand, context)

                    if demand.idempotency_key:
                        await cur.execute(
                            """
                            SELECT request_id, status, observation_id
                            FROM wa_location_request
                            WHERE idempotency_key = %s
                            """,
                            (demand.idempotency_key,),
                        )
                        existing = await cur.fetchone()
                        if existing:
                            return WaLocationRequestOutcome(
                                request_id=existing["request_id"],
                                status=(
                                    "location_available"
                                    if existing["status"] in {"fulfilled", "delivered"}
                                    else "waiting_for_rider"
                                ),
                            )

                    await cur.execute(
                        """
                        INSERT INTO wa_location_request (
                            idempotency_key, order_number, dispatch_id, rider_id,
                            location_requested_by, requester_id, callback_url
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING request_id
                        """,
                        (
                            demand.idempotency_key,
                            context.order_number,
                            context.dispatch_id,
                            context.rider_id,
                            demand.location_requested_by,
                            demand.requester_id,
                            demand.callback_url,
                        ),
                    )
                    request_id = (await cur.fetchone())["request_id"]

                    await cur.execute(
                        """
                        SELECT observation_id, source
                        FROM wa_location_observation
                        WHERE order_number = %s
                          AND dispatch_id = %s
                          AND rider_id = %s
                          AND observed_at >= %s
                        ORDER BY observed_at DESC
                        LIMIT 1
                        """,
                        (
                            context.order_number,
                            context.dispatch_id,
                            context.rider_id,
                            utcnow() - FRESHNESS,
                        ),
                    )
                    observation = await cur.fetchone()
                    if observation:
                        await self._fulfil(cur, request_id, observation["observation_id"])
                        decision = ("route", request_id, context, observation["source"])
                    else:
                        await cur.execute(
                            """
                            SELECT request_id
                            FROM wa_location_request
                            WHERE order_number = %s
                              AND dispatch_id = %s
                              AND rider_id = %s
                              AND status = 'pending'
                              AND wa_location_prompt_time >= %s
                            ORDER BY wa_location_prompt_time DESC
                            LIMIT 1
                            """,
                            (
                                context.order_number,
                                context.dispatch_id,
                                context.rider_id,
                                utcnow() - PROMPT_COOLDOWN,
                            ),
                        )
                        recent_prompt = await cur.fetchone()
                        if recent_prompt:
                            decision = ("wait", request_id, context, None)
                        else:
                            await cur.execute(
                                """
                                UPDATE wa_location_request
                                SET wa_location_prompt_time = now(), updated_at = now()
                                WHERE request_id = %s
                                """,
                                (request_id,),
                            )
                            decision = ("prompt", request_id, context, None)

        assert decision is not None
        action, request_id, context, source = decision
        if action == "route":
            route_status = await self.route_fulfilled_request(request_id)
            if route_status == "expired":
                raise WaLocationConflict("delivery_not_inflight")
            if route_status != "delivered":
                raise WaLocationCallbackDeliveryFailed()
            return WaLocationRequestOutcome(
                request_id=request_id, status="location_available", source=source
            )
        if action == "wait":
            return WaLocationRequestOutcome(
                request_id=request_id, status="waiting_for_rider"
            )

        if not await self._exact_inflight_assignment_exists(context):
            await self._expire(request_id, "delivery_not_inflight")
            raise WaLocationConflict("delivery_not_inflight")

        try:
            sent = await self._wa_client.request_location(
                to=context.rider_id,
                text=(
                    "Please share your current location so we can update the "
                    "person waiting for your delivery."
                ),
            )
        except Exception as exc:
            await self._mark_prompt_failed(request_id, type(exc).__name__)
            raise

        await self._save_prompt_message_id(request_id, sent.id)
        return WaLocationRequestOutcome(request_id=request_id, status="rider_prompted")

    async def receive_whatsapp_location(self, receipt: WhatsAppLocationReceipt) -> int:
        """Persist one correlated current location and route all pending demands."""

        pool = await pg_settings.get_pool()
        request_ids: list[UUID] = []
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT request_id, order_number, dispatch_id, rider_id
                        FROM wa_location_request
                        WHERE wa_request_message_id = %s
                          AND rider_id = %s
                          AND status = 'pending'
                        """,
                        (receipt.reply_to_message_id, receipt.rider_id),
                    )
                    correlated = await cur.fetchone()
                    if not correlated:
                        await cur.execute(
                            """
                            SELECT request_id, order_number, dispatch_id, rider_id
                            FROM wa_location_request
                            WHERE rider_id = %s AND status = 'pending'
                            ORDER BY wa_location_req_time ASC
                            """,
                            (receipt.rider_id,),
                        )
                        candidates = await cur.fetchall()
                        candidates = [
                            candidate
                            for candidate in candidates
                            if await self._exact_inflight_assignment_exists_in_cursor(
                                cur,
                                _DeliveryContext(
                                    order_number=candidate["order_number"],
                                    customer_id="",
                                    dispatch_id=candidate["dispatch_id"],
                                    rider_id=candidate["rider_id"],
                                    dispatch_status="",
                                    admins=[],
                                ),
                            )
                        ]
                        if len(candidates) != 1:
                            logger.info(
                                "Ignoring ambiguous or unsolicited WaLocation response for rider={}",
                                receipt.rider_id,
                            )
                            return 0
                        correlated = candidates[0]

                    context = _DeliveryContext(
                        order_number=correlated["order_number"],
                        customer_id="",
                        dispatch_id=correlated["dispatch_id"],
                        rider_id=correlated["rider_id"],
                        dispatch_status="",
                        admins=[],
                    )
                    if not await self._exact_inflight_assignment_exists_in_cursor(cur, context):
                        await self._expire_pending_for_context(cur, context)
                        return 0

                    await cur.execute(
                        """
                        INSERT INTO wa_location_observation (
                            order_number, dispatch_id, rider_id, latitude, longitude,
                            source, observed_at, wa_inbound_message_id
                        ) VALUES (%s, %s, %s, %s, %s, 'whatsapp_current', %s, %s)
                        ON CONFLICT (wa_inbound_message_id) WHERE wa_inbound_message_id IS NOT NULL
                        DO NOTHING
                        RETURNING observation_id
                        """,
                        (
                            context.order_number,
                            context.dispatch_id,
                            context.rider_id,
                            receipt.latitude,
                            receipt.longitude,
                            receipt.observed_at,
                            receipt.inbound_message_id,
                        ),
                    )
                    inserted = await cur.fetchone()
                    if not inserted:
                        return 0
                    observation_id = inserted["observation_id"]
                    await cur.execute(
                        """
                        UPDATE wa_location_request
                        SET status = 'fulfilled', observation_id = %s,
                            wa_location_res_time = now(), updated_at = now()
                        WHERE order_number = %s AND dispatch_id = %s AND rider_id = %s
                          AND status = 'pending'
                        RETURNING request_id
                        """,
                        (
                            observation_id,
                            context.order_number,
                            context.dispatch_id,
                            context.rider_id,
                        ),
                    )
                    request_ids = [row["request_id"] for row in await cur.fetchall()]

        for request_id in request_ids:
            await self.route_fulfilled_request(request_id)
        return len(request_ids)

    async def observe_restaurant_confirmation(
        self, observation: RestaurantConfirmationObservation
    ) -> int:
        """Persist an explicitly approximate restaurant observation and route it."""

        context = _DeliveryContext(
            order_number=observation.order_number,
            customer_id="",
            dispatch_id=observation.dispatch_id,
            rider_id=observation.rider_id,
            dispatch_status="",
            admins=[],
        )
        if not await self._exact_inflight_assignment_exists(context):
            logger.info(
                "Skipping restaurant confirmation WaLocation observation for inactive order={}",
                observation.order_number,
            )
            return 0

        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        INSERT INTO wa_location_observation (
                            order_number, dispatch_id, rider_id, latitude, longitude,
                            source, observed_at
                        ) VALUES (%s, %s, %s, %s, %s, 'restaurant_confirmation', %s)
                        RETURNING observation_id
                        """,
                        (
                            observation.order_number,
                            observation.dispatch_id,
                            observation.rider_id,
                            observation.latitude,
                            observation.longitude,
                            observation.observed_at,
                        ),
                    )
                    observation_id = (await cur.fetchone())["observation_id"]
                    await cur.execute(
                        """
                        UPDATE wa_location_request
                        SET status = 'fulfilled', observation_id = %s,
                            wa_location_res_time = now(), updated_at = now()
                        WHERE order_number = %s AND dispatch_id = %s AND rider_id = %s
                          AND status = 'pending'
                        RETURNING request_id
                        """,
                        (
                            observation_id,
                            observation.order_number,
                            observation.dispatch_id,
                            observation.rider_id,
                        ),
                    )
                    request_ids = [row["request_id"] for row in await cur.fetchall()]

        for request_id in request_ids:
            await self.route_fulfilled_request(request_id)
        return len(request_ids)

    async def route_fulfilled_request(self, request_id: UUID) -> str:
        """Send a fulfilled observation only while its exact job remains inflight."""

        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT req.request_id, req.order_number, req.dispatch_id, req.rider_id,
                           req.requester_id, req.location_requested_by, req.callback_url,
                           summary.customer_id, obs.latitude, obs.longitude,
                           obs.source, obs.observed_at
                    FROM wa_location_request req
                    JOIN wa_location_observation obs ON obs.observation_id = req.observation_id
                    JOIN delivery_summary summary ON summary.order_number = req.order_number
                    WHERE req.request_id = %s AND req.status = 'fulfilled'
                    """,
                    (request_id,),
                )
                row = await cur.fetchone()
        if not row:
            return "missing"

        context = _DeliveryContext(
            order_number=row["order_number"],
            customer_id=row["customer_id"],
            dispatch_id=row["dispatch_id"],
            rider_id=row["rider_id"],
            dispatch_status="",
            admins=[],
        )
        if not await self._exact_inflight_assignment_exists(context):
            await self._expire(request_id, "delivery_not_inflight")
            return "expired"

        try:
            await self._validate_public_callback_url(row["callback_url"])
            payload = WaLocationCallbackPayload(
                request_id=row["request_id"],
                order_number=row["order_number"],
                customer_id=row["customer_id"],
                rider_id=row["rider_id"],
                location_requested_by=row["location_requested_by"],
                requester_id=row["requester_id"],
                location={
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "source": row["source"],
                    "observed_at": row["observed_at"].isoformat(),
                },
            ).model_dump(mode="json")
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(10.0),
                trust_env=False,
            ) as client:
                response = await client.post(row["callback_url"], json=payload)
                response.raise_for_status()
        except Exception as exc:
            await self._save_route_error(request_id, type(exc).__name__)
            return "failed"
        await self._mark_delivered(request_id)
        return "delivered"

    async def _validate_public_callback_url(self, callback_url: str) -> None:
        """Reject local/private callback targets before each outbound delivery."""

        parsed = urlsplit(callback_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise WaLocationForbidden("callback_url_not_public_https")

        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise WaLocationForbidden("callback_url_not_public_https") from exc
        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise WaLocationForbidden("callback_url_unresolvable") from exc
        if not addresses:
            raise WaLocationForbidden("callback_url_unresolvable")
        for address in addresses:
            host = address[4][0]
            if not ipaddress.ip_address(host).is_global:
                raise WaLocationForbidden("callback_url_not_public")

    def _validate_rest_ref(self, demand: WaLocationDemand) -> None:
        if demand.order_number.split("-", 1)[0].upper() != demand.rest_ref.upper():
            raise WaLocationForbidden("rest_ref_order_mismatch")

    async def _load_delivery_context(self, cur: Any, order_number: str) -> _DeliveryContext:
        await cur.execute(
            """
            SELECT summary.order_number, summary.customer_id, detail.dispatch_id,
                   dispatch.rider_id, dispatch.status AS dispatch_status,
                   COALESCE(restaurant.admins, ARRAY[]::TEXT[]) AS admins
            FROM delivery_summary summary
            JOIN delivery_detail detail ON detail.order_number = summary.order_number
            JOIN delivery_dispatch dispatch ON dispatch.dispatch_id = detail.dispatch_id
            LEFT JOIN restaurant_master restaurant ON restaurant.rest_ref = summary.rest_ref
            WHERE summary.order_number = %s
            """,
            (order_number,),
        )
        row = await cur.fetchone()
        if not row:
            raise WaLocationNotFound()
        return _DeliveryContext(
            order_number=row["order_number"],
            customer_id=row["customer_id"],
            dispatch_id=row["dispatch_id"],
            rider_id=row["rider_id"],
            dispatch_status=row["dispatch_status"],
            admins=list(row["admins"] or []),
        )

    async def _validate_demand(
        self, cur: Any, demand: WaLocationDemand, context: _DeliveryContext
    ) -> None:
        if demand.location_requested_by == "customer":
            if demand.requester_id != context.customer_id:
                raise WaLocationForbidden("customer_order_mismatch")
        elif demand.location_requested_by == "restaurant_admin":
            if demand.requester_id not in context.admins:
                raise WaLocationForbidden("restaurant_admin_not_authorized")
        else:  # defensive: Pydantic has already limited the public value
            raise WaLocationForbidden("unsupported_requester")

        if not await self._exact_inflight_assignment_exists_in_cursor(cur, context):
            raise WaLocationConflict("delivery_not_inflight")

        if (
            demand.location_requested_by == "customer"
            and context.dispatch_status != "pickedup"
        ):
            raise WaLocationConflict("food_not_picked_up")
        if (
            demand.location_requested_by == "restaurant_admin"
            and context.dispatch_status not in {"assigned", "pickedup"}
        ):
            raise WaLocationConflict("delivery_not_active")

    async def _exact_inflight_assignment_exists_in_cursor(
        self, cur: Any, context: _DeliveryContext
    ) -> bool:
        await cur.execute(
            """
            SELECT 1
            FROM delivery_inflight
            WHERE order_number = %s AND dispatch_id = %s AND rider_id = %s
            FOR KEY SHARE
            """,
            (context.order_number, context.dispatch_id, context.rider_id),
        )
        return await cur.fetchone() is not None

    async def _exact_inflight_assignment_exists(self, context: _DeliveryContext) -> bool:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                return await self._exact_inflight_assignment_exists_in_cursor(cur, context)

    async def _fulfil(self, cur: Any, request_id: UUID, observation_id: UUID) -> None:
        await cur.execute(
            """
            UPDATE wa_location_request
            SET status = 'fulfilled', observation_id = %s,
                wa_location_res_time = now(), updated_at = now()
            WHERE request_id = %s
            """,
            (observation_id, request_id),
        )

    async def _save_prompt_message_id(self, request_id: UUID, message_id: str) -> None:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE wa_location_request SET wa_request_message_id = %s, updated_at = now() WHERE request_id = %s",
                    (message_id, request_id),
                )
            await conn.commit()

    async def _mark_prompt_failed(self, request_id: UUID, reason: str) -> None:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE wa_location_request
                    SET status = 'failed', wa_location_prompt_time = NULL,
                        route_error = %s, updated_at = now()
                    WHERE request_id = %s
                    """,
                    (reason, request_id),
                )
            await conn.commit()

    async def _expire(self, request_id: UUID, reason: str) -> None:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE wa_location_request
                    SET status = 'expired', route_error = %s, updated_at = now()
                    WHERE request_id = %s AND status IN ('pending', 'fulfilled')
                    """,
                    (reason, request_id),
                )
            await conn.commit()

    async def _expire_pending_for_context(self, cur: Any, context: _DeliveryContext) -> None:
        await cur.execute(
            """
            UPDATE wa_location_request
            SET status = 'expired', route_error = 'delivery_not_inflight', updated_at = now()
            WHERE order_number = %s AND dispatch_id = %s AND rider_id = %s
              AND status = 'pending'
            """,
            (context.order_number, context.dispatch_id, context.rider_id),
        )

    async def _save_route_error(self, request_id: UUID, reason: str) -> None:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE wa_location_request
                    SET route_attempt_count = route_attempt_count + 1,
                        last_route_attempt_time = now(), route_error = %s,
                        updated_at = now()
                    WHERE request_id = %s AND status = 'fulfilled'
                    """,
                    (reason, request_id),
                )
            await conn.commit()

    async def _mark_delivered(self, request_id: UUID) -> None:
        pool = await pg_settings.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE wa_location_request
                    SET status = 'delivered', routed_at = now(), route_error = NULL,
                        route_attempt_count = route_attempt_count + 1,
                        last_route_attempt_time = now(), updated_at = now()
                    WHERE request_id = %s AND status = 'fulfilled'
                    """,
                    (request_id,),
                )
            await conn.commit()
