"""Open entry point for on-demand customer/admin rider-location requests."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config import _async_wa_client, logger
from ordelo.wa_location import (
    WaLocation,
    WaLocationCallbackDeliveryFailed,
    WaLocationConflict,
    WaLocationForbidden,
    WaLocationNotFound,
)
from ordelo_datamodels.wa_location_pymodels import WaLocationDemand

router = APIRouter(tags=["wa_location"])


def _http_error_for(exc: Exception) -> HTTPException:
    if isinstance(exc, WaLocationNotFound):
        return HTTPException(status_code=404, detail={"code": exc.code})
    if isinstance(exc, WaLocationForbidden):
        return HTTPException(status_code=403, detail={"code": exc.code})
    if isinstance(exc, WaLocationConflict):
        return HTTPException(status_code=409, detail={"code": exc.code})
    if isinstance(exc, WaLocationCallbackDeliveryFailed):
        return HTTPException(status_code=502, detail={"code": exc.code})
    return HTTPException(status_code=500, detail={"code": "wa_location_failed"})


@router.post("/wa-request-location")
async def request_location(
    request: Request, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Create one open, authority-checked WaLocation demand."""

    raw_body = await request.body()
    try:
        demand = WaLocationDemand.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_payload"}) from exc

    try:
        outcome = await WaLocation(wa_client=_async_wa_client).request(
            demand, schedule=background_tasks.add_task
        )
    except Exception as exc:
        http_error = _http_error_for(exc)
        if http_error.status_code == 500:
            # Every other WaLocation failure is a typed, expected outcome
            # (404/403/409/502) already surfaced to the caller by its code.
            # Only this catch-all case is genuinely unexpected, and until now
            # it was logged nowhere -- the underlying exception was visible
            # only as its class name in wa_location_request.route_error.
            logger.exception(
                "Unhandled WaLocation failure for order={} rest_ref={} "
                "requester={}: {}",
                demand.order_number,
                demand.rest_ref,
                demand.requester_id,
                exc,
            )
        raise http_error from exc

    return JSONResponse(
        status_code=200 if outcome.status == "location_available" else 202,
        content=outcome.model_dump(mode="json"),
    )
