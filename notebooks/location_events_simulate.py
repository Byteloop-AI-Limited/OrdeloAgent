# %%
from config import pg_settings, project_settings
from psycopg_pool import ConnectionPool
from datetime import datetime
import requests

# %% Test params

url = f"DummyValue/location-hooks/pub"
topic = "owntracks/447448440754/447448440754-e153845d621d497ea780a9ce5647d822/event"

# %% Rest enter

payload = {
    "lon": 0.096501,
    "acc": 2,
    "wtst": 1739801838,
    "event": "enter",
    "rid": "rest",
    "desc": "home",
    "topic": topic,
    "lat": 51.354255,
    "t": "c",
    "tst": 1739802742,
    "tid": "23",
    "_type": "transition",
}

requests.post(url, json=payload)

# %%
from config import logger

# %% rest leave
payload = {
    "lon": 0.096501,
    "acc": 2,
    "wtst": 1739801838,
    "event": "leave",
    "rid": "rest",
    "desc": "home",
    "topic": topic,
    "lat": 51.354255,
    "t": "c",
    "tst": 1739802742,
    "tid": "23",
    "_type": "transition",
}
requests.post(url, json=payload)

# %% cust enter
payload = {
    "lon": 0.096501,
    "acc": 2,
    "wtst": 1739801838,
    "event": "enter",
    "rid": "cust",
    "desc": "home",
    "topic": topic,
    "lat": 51.354255,
    "t": "c",
    "tst": 1739802742,
    "tid": "23",
    "_type": "transition",
}

requests.post(url, json=payload)


# %% Debug standard location update
from ordelo_datamodels.location_pymodels import Location

payload = {
    "batt": 25,
    "lon": 0.09078,
    "acc": 23,
    "bs": 1,
    "inrids": ["rest"],
    "vac": 13,
    "inregions": ["rest"],
    "lat": 51.360026,
    "topic": topic,
    "t": "c",
    "conn": "m",
    "m": 2,
    "tst": 1740670305,
    "alt": 69,
    "_type": "location",
    "tid": "23",
}
location = Location(**payload)

requests.post(url, json=payload)
# %%

# %%
