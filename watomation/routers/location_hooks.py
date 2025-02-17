from fastapi import APIRouter, Request, HTTPException
from loguru import logger
import psycopg
from pydantic import BaseModel
import json
import base64
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["location_hooks"])
templates = Jinja2Templates(directory="/home/basal/PycharmProjects/OrdeloAgent/watomation/routers/templates")

class Location(BaseModel):
    # Note: You'll need to add the fields from your Location model here
    pass

def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"

@router.get("/config")
async def get_config(request: Request):
    waypoints = [
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "h0me",
            "desc": "home",
            "rad": 1,
            "lat": 51.354107,
            "lon": 0.095921
        },
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "tesco",
            "desc": "tesco",
            "rad": 5,
            "lat": 51.37367242361126,
            "lon": 0.09653313354081415
        },
        {
            "_type": "waypoint",
            "tst": 1708625557,
            "rid": "Gym",
            "desc": "Gym",
            "rad": 5,
            "lat": 51.37355872938557,
            "lon": 0.09813191393856706
        },
    ]

    start_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": True,
        "usePassword" : False,
        "monitoring": 2,
        "username": "447448440754",
        "deviceId": "447448440754-order123",
        "password": "",
        "url": "https://live-track.byteloop.ai/pub",
        "locatorDisplacement": 10,
        "locatorInterval" : 10,
        "waypoints": waypoints
    }
    
    stop_job_config = {
        "_type": "configuration",
        "mode": 3,
        "allowRemoteLocation": False,
        "usePassword" : False,
        "monitoring": -1,
        "username": "NA",
        "password": "",
        "url": "",
    }
    
    start_href = generate_config_href(start_job_config)
    stop_href = generate_config_href(stop_job_config)
    
    return templates.TemplateResponse("get-config.html", {"request": request, "start_href": start_href, "stop_href": stop_href})

@router.post("/")
async def receive_pub(request: Request):
    payload = await request.json()
    pool = request.app.state.pool
    location = Location(**payload)
    print(location)

    try:
        # Acquire a connection from the pool
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    # Build dynamic query using fields from location
                    columns = ", ".join(location.dict().keys())
                    placeholders = ", ".join([f"%({key})s" for key in location.dict().keys()])
                    query = f"""
                        INSERT INTO driver_location ({columns})
                        VALUES ({placeholders})
                        RETURNING *;
                    """
                    await cur.execute(query, location.dict())
                    result = await cur.fetchone()
                    logger.info(result)
                    return {"result": result}
    except Exception as e:
        # Log additional debug information for troubleshooting
        debug_info = {
            'query': query,
            'payload': location.dict(),
            'error': str(e)
        }
        print('DEBUG:', debug_info)
        raise HTTPException(status_code=500, detail=f"Insertion failed. Debug info: {debug_info}")
