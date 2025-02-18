# %%
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
import uvicorn
import json
import asyncio
from typing import Dict
import paho.mqtt.client as mqtt
from datetime import datetime
import base64
from fastapi.templating import Jinja2Templates

from pywa import WhatsApp
import pandas as pd
import pickle
from config import project_settings, logger, waba_business_settings

wa = WhatsApp(
    business_account_id=waba_business_settings.account_id,
    token=waba_business_settings.token,
    phone_id=waba_business_settings.phone_id
)
recipient = "447448440754"

root = project_settings.project_root

# %%
app = FastAPI()
templates = Jinja2Templates(directory="utils_common/live_location/templates")

# Endpoint to handle incoming POST requests on /pub
@app.post("/pub")
async def receive_pub(request: Request):
    try:
        # Retrieve and print the incoming request JSON payload
        payload = await request.json()
        # if '_type' in payload and payload['_type'] == 'transition':
        if '_type' in payload:
            wa.send_text(
                to=recipient,
                text=json.dumps(payload)
            )
        # Convert Unix timestamp to readable format
        if 'tst' in payload:
            timestamp = datetime.fromtimestamp(payload['tst'])
            payload['readable_time'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        print("Received JSON payload:", json.dumps(payload, indent=4))

        # Dump payload into a pickle file
        pickle_file_path = f"{root}/data/live_location.pkl"
        try:
            with open(pickle_file_path, 'ab') as pickle_file:
                pickle.dump(payload, pickle_file)
            print(f"Payload dumped to {pickle_file_path}")
        except Exception as e:
            print(f"Error dumping payload to pickle file: {e}")

        return {"message": "Payload received successfully", "payload": payload}
        
    except Exception as e:
        print("Error while handling request:", str(e))
        return {"error": "Invalid request or JSON payload"}


# Insert the function definition for generating the configuration URL
def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"


@app.get("/config")
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


@app.post("/test-sbase")
async def test_sbase(request: Request):
    payload = await request.json()
    print(payload)
    return payload


if __name__ == "__main__":
    uvicorn.run(
        "utils_common.live_location.app_live_location_tracker:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True
        )    
