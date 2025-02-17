# %%
from config import pg_settings
from psycopg_pool import ConnectionPool
from datetime import datetime, timezone
# %%
pool = ConnectionPool(pg_settings.db_uri)

# %%
with pool.connection() as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rider_location_event (topic, rider_id, order_number, tst, res_enter_dtts)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (topic) DO UPDATE SET
                res_enter_dtts = EXCLUDED.res_enter_dtts
            """,
            (1, 1231, 1, 1739802745, "2025-02-17 14:32:07", 1231, 1231)
        )
        conn.commit()



# %%
import requests 

url = "https://live-track.byteloop.ai/location-hooks/pub"
payload = {
            'lon': 0.096501, 
            'acc': 2, 
            'wtst': 1739801838, 
            'event': 'enter', 
            'rid': 'rest', 
            'desc': 'home', 
            'topic': 'owntracks/447448440754/447448440754-test123/event', 
            'lat': 51.354255, 
            't': 'c', 
            'tst': 1739802742, 
            'tid': '23', 
            '_type': 'transition'
        }
payload = {
            'lon': 0.096501, 
            'acc': 2, 
            'wtst': 1739801838, 
            'event': 'leave', 
            'rid': 'rest', 
            'desc': 'home', 
            'topic': 'owntracks/447448440754/447448440754-test123/event', 
            'lat': 51.354255, 
            't': 'c', 
            'tst': 1739802742, 
            'tid': '23', 
            '_type': 'transition'
        }

payload = {
            'lon': 0.096501, 
            'acc': 2, 
            'wtst': 1739801838, 
            'event': 'leave', 
            'rid': 'cust', 
            'desc': 'home', 
            'topic': 'owntracks/447448440754/447448440754-test123/event', 
            'lat': 51.354255, 
            't': 'c', 
            'tst': 1739802742, 
            'tid': '23', 
            '_type': 'transition'
        }
requests.post(url, json=payload)