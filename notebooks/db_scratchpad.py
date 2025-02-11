# %%
from config import pg_settings
from psycopg_pool import AsyncConnectionPool

# %%
pool = AsyncConnectionPool(
    conninfo=pg_settings.db_uri,
    kwargs=pg_settings.connection_kwargs,
    open=False,
)

# %%
import base64 
import json

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
        "locatorInterval" : 10
    }

def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"

generate_config_href(start_job_config)


# %%
import httpx 
from utils_common.db_utils.sbase_rest_ops import sql_to_supabase_rest

_condition = sql_to_supabase_rest(driver_id__like='7448440754')
_condition
# %%
async with httpx.AsyncClient() as client:
    try:
        response = await client.get(
            # f"{pg_settings.rest_url}/rest/v1/driver_location?{_condition}", 
            f"{pg_settings.rest_url}/rest/v1/driver_location", 
            headers=pg_settings.headers
        )
        response.raise_for_status()
        # Parse the response
        response_data = response.json()
        print(response_data)
    except:
        print("Error: ", response.status_code, response.text)
        