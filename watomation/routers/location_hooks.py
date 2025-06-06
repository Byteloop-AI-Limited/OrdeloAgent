"""
Location hooks router for OrdeloAgent FastAPI service.
    . Defines endpoints for location-related webhook events (OwnTracks, transitions)
    . Processes location transitions and updates rider_location_event table
    . Exposes endpoints for live location tracking and map URLs
    . Notifies users of delivery progress via WhatsApp
    . Follows extensible webhook and DB update patterns
"""

# %%
from fastapi import APIRouter, Request, Depends, Path, HTTPException
from fastapi.responses import RedirectResponse
from loguru import logger
import psycopg
import json
import base64
from fastapi import Path
from ordelo_datamodels.location_pymodels import Location
from config import _async_wa_client, pg_settings
import re
from datetime import datetime, timezone
from pywa.types import ButtonUrl
from ordelo.agent_app_handlers import get_live_map_location_url
from utils_common.db_utils.sbase_pool_ops import insert_model_to_db


# %% Define Dependancies and routes
async def get_payload(request: Request):
    return await request.json()


router = APIRouter(tags=["location_hooks"])


# %%
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"


# %% Define functions


# %% process location event


async def process_location_transition(payload):
    """
    Process a location transition event.

    Acquire a connection from the pool, build a dynamic query using fields from the payload,
    execute the query with the payload object as arguments, and return the result.

    If an exception occurs, log additional debug information for troubleshooting, and raise
    an HTTPException with a 500 status code.

    :param pool: A connection pool to use for the database query
    :param payload: A Location object to be inserted into the rider_location table
    :return: A JSON object containing the result of the query
    """
    tst = payload["tst"]
    dtts = datetime.fromtimestamp(tst, tz=timezone.utc)
    topic = payload["topic"]
    event = payload["event"]
    rid = payload["rid"]

    match = re.match(
        r"owntracks/(?P<rider_id>[^/]+)/(?P<recipient>[^-]+)-(?P<order_number>[^/]+)/event$",
        topic,
    )
    if match:
        rider_id = match.group("rider_id")
        recipient = match.group("recipient")
        order_number = match.group("order_number")

    pool = await pg_settings.get_pool()
    async with pool.connection() as conn:
        # Initialize with a default value
        update_statement = None
        update_vals = (dtts, topic)

        if event == "enter" and rid == "rest":
            # Updates the database based on rider location events:
            # - For restaurant enter: Creates new record or updates existing one
            # - For restaurant leave: Records departure time
            # - For customer enter/leave: Records respective timestamps
            # All updates after initial entry require a valid restaurant entry timestamp
            update_statement = """
                INSERT INTO rider_location_event (topic, rider_id, order_number, tst, res_enter_dtts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (topic) DO UPDATE SET
                    res_enter_dtts = %s,
                    res_leave_dtts = NULL,
                    cust_enter_dtts = NULL,
                    cust_leave_dtts = NULL
                """
            update_vals = (topic, rider_id, order_number, tst, dtts, dtts)

        elif event == "leave" and rid == "rest":
            update_statement = """
                UPDATE rider_location_event
                SET res_leave_dtts = %s
                WHERE topic = %s AND res_enter_dtts IS NOT NULL AND res_leave_dtts IS NULL;
            """

        elif event == "enter" and rid == "cust":
            update_statement = """
                UPDATE rider_location_event
                SET cust_enter_dtts = %s
                WHERE topic = %s AND res_enter_dtts IS NOT NULL AND cust_enter_dtts IS NULL;
            """
        elif event == "leave" and rid == "cust":
            update_statement = """
                UPDATE rider_location_event
                SET cust_leave_dtts = %s
                WHERE topic = %s AND res_enter_dtts IS NOT NULL AND cust_leave_dtts IS NULL;
            """

        async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            if update_statement is None:
                raise ValueError(
                    f"No valid update statement found for event={event} and rid={rid}"
                )
            await cur.execute(update_statement, update_vals)
            await conn.commit()

    logger.info(f"transition event processed:{topic}")

    return True


# %% Define paths - live location on map
@router.get(
    "/live-location-map/{order_number}",
    response_class=RedirectResponse,
    summary="Redirect to Live Location Map",
    description="Redirects the client to a Google Maps URL for the rider's current location",
)
async def live_location_map(
    order_number: str = Path(..., description="The order number to track"),
):
    live_map_url = await get_live_map_location_url(order_number)
    if live_map_url is None:
        raise HTTPException(status_code=404, detail="No live location found")

    return live_map_url


# %% Define Paths - location updates and transition events
@router.post(
    "/pub",
    summary="OwnTracks Location Webhook",
    description="""
    
    Handles two types of events:
    - Location events: Records the rider's current position
    - Transition events: Records when riders enter/leave specific zones
    """,
    response_description="Successful processing of the location event",
    responses={
        200: {"description": "Location event processed successfully"},
        500: {"description": "Error processing location event"},
    },
)
async def receive_pub(
    payload: dict = Depends(get_payload),
):
    """
    Webhook to receive location events from OwnTracks

    This endpoint receives location events from OwnTracks and processes them
    according to their type. If the event is a transition, it calls
    `process_location_transition` to update the transition times in the database.
    If the event is a location, it calls `process_location` to insert the location
    into the database.

    :param payload: The JSON payload from the OwnTracks location event
    """
    logger.info(payload)

    if payload.get("_type") == "transition":
        await process_location_transition(payload)
        return

    elif payload.get("_type") == "location":
        location = Location(**payload)
        await insert_model_to_db(
            table_name="rider_location",
            model_instance=location,
        )
        return


# %% listen for location events


@router.post(
    "/notify-rider-location-event",
    summary="Notify Rider Location Events To Customer",
    description="Routes Rider's location events, including zone transitions and status updates",
    response_description="Successful processing of the rider location event",
    responses={
        200: {"description": "Location event processed successfully"},
        500: {"description": "Error processing location event"},
    },
)
async def notify_rider_location_event(request: Request):
    """
    Post requests are made via db webhooks based on the updates made in `process_location_transition`
    """
    payload = await request.json()

    # Unpack location event row
    location_event_new = payload.get("location_event_new")
    order_number = location_event_new.get("order_number")
    rider_id = location_event_new.get("rider_id")
    # recipient = location_event_new.get('recipient')
    recipient = rider_id

    response = await live_location_map(order_number=order_number)
    live_map_url = response.get("current_location", None)

    if live_map_url is None:
        return
    # Unpack changed fields
    changed_fields = payload.get("changed_fields", {})

    if changed_fields is not None:
        if "res_leave_dtts" in changed_fields.keys():
            if live_map_url is not None:
                await _async_wa_client.send_message(
                    to=recipient,
                    header=f"{order_number} Update",
                    reply_to_message_id=None,
                    text="""
                    Our delivery driver has left the restaurant
                    """,
                    buttons=ButtonUrl(title="Live Location", url=live_map_url),
                )
            else:
                await _async_wa_client.send_message(
                    to=recipient,
                    header=f"{order_number} Update",
                    text="Our delivery driver has left the restaurant",
                )

        elif "res_enter_dtts" in changed_fields.keys():
            await _async_wa_client.send_message(
                to=recipient,
                header=f"{order_number} Update",
                text="Our delivery driver has entered the restaurant",
            )

        elif "cust_enter_dtts" in changed_fields.keys():
            await _async_wa_client.send_message(
                to=recipient,
                header=f"{order_number} Update",
                text="Our delivery rider is near you",
            )

        elif "cust_leave_dtts" in changed_fields.keys():
            await _async_wa_client.send_message(
                to=recipient,
                header=f"{order_number} Update",
                text="Our delivery rider has left your location",
            )

    # location = Location(**payload)
    # logger.info(location)
    return


# %% get config unused

# @router.get("/config")
# async def get_config(request: Request):
#     waypoints = [
#         {
#             "_type": "waypoint",
#             "tst": 1708625557,
#             "rid": "h0me",
#             "desc": "home",
#             "rad": 1,
#             "lat": 51.354107,
#             "lon": 0.095921
#         },
#         {
#             "_type": "waypoint",
#             "tst": 1708625557,
#             "rid": "tesco",
#             "desc": "tesco",
#             "rad": 5,
#             "lat": 51.37367242361126,
#             "lon": 0.09653313354081415
#         },
#         {
#             "_type": "waypoint",
#             "tst": 1708625557,
#             "rid": "Gym",
#             "desc": "Gym",
#             "rad": 5,
#             "lat": 51.37355872938557,
#             "lon": 0.09813191393856706
#         },
#     ]

#     start_job_config = {
#         "_type": "configuration",
#         "mode": 3,
#         "allowRemoteLocation": True,
#         "usePassword" : False,
#         "monitoring": 2,
#         "username": "447448440754",
#         "deviceId": "447448440754-order123",
#         "password": "",
#         "url": "https://live-track.byteloop.ai/pub",
#         "locatorDisplacement": 10,
#         "locatorInterval" : 10,
#         "waypoints": waypoints
#     }

#     stop_job_config = {
#         "_type": "configuration",
#         "mode": 3,
#         "allowRemoteLocation": False,
#         "usePassword" : False,
#         "monitoring": -1,
#         "username": "NA",
#         "password": "",
#         "url": "",
#     }

#     start_href = generate_config_href(start_job_config)
#     stop_href = generate_config_href(stop_job_config)

#     return templates.TemplateResponse("get-config.html", {"request": request, "start_href": start_href, "stop_href": stop_href})
