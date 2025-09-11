# %%

from datetime import datetime
from config import _async_wa_client as wa

start_job_config = {
    "_type": "configuration",
    "mode": 3,
    "allowRemoteLocation": True,
    "usePassword": False,
    # "url": f"{project_settings.base_url}/location-hooks/pub",
    "url": "https://agent.ordelo.app/echo",
    "monitoring": 2,
    "locatorDisplacement": 1,
    "locatorInterval": 3,
    "username": "test",
    "deviceId": "testRider-123",
    "password": "",
}

stop_job_config = {
    "_type": "configuration",
    "mode": 3,
    "allowRemoteLocation": False,
    # "usePassword": False,
    # "username": "NA",
    "device_id": "NA",
    # "password": "",
    "monitoring": -1,
    "url": "",
}


# %%
from pywa.types import ButtonUrl
import json
import base64


def generate_config_href(config: dict) -> str:
    config_json = json.dumps(config)
    config_base64 = base64.b64encode(config_json.encode()).decode()
    return f"owntracks:///config?inline={config_base64}"


# recipient = "447448440754"
recipient = "447438568101"
# %% Start test job config

job_config_str = generate_config_href(start_job_config)
# job_config_str
await wa.send_message(
    to=recipient,
    text="This is test message. Click the button to test live tracking.",
    buttons=ButtonUrl(title="Start live tracking", url=job_config_str),
)

# %% Stop test job config

job_config_str = generate_config_href(stop_job_config)

await wa.send_message(
    to=recipient,
    text="This is test message. Click the button to test live tracking.",
    buttons=ButtonUrl(title="Stop live tracking", url=job_config_str),
)

# %%

await wa.send_message(
    to=recipient,
    text="This is test message. Click the button to test live tracking.",
)
