"""
Test script for the OwnTracks Webhook edge function.
  . Simulates an OwnTracks location payload
  . Posts JSON data to the Deno server and validates the response
  Functions/Classes
    . test_owntracks_webhook
"""

import requests
import json
import time

# Local Deno server address (default)
BASE_URL = "http://localhost:8000"


def test_owntracks_webhook():
    print("Testing OwnTracks Webhook...")

    # Example OwnTracks payload
    payload = {
        "_type": "location",
        "acc": 35,
        "alt": 52,
        "batt": 89,
        "conn": "w",
        "lat": 51.5074,
        "lon": -0.1278,
        "t": "u",
        "tid": "rt",
        "tst": int(time.time()),
        "vac": 10,
        "vel": 0,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer YOUR_SUPABASE_ANON_KEY",  # Optional: if you check headers in TS
    }

    try:
        response = requests.post(BASE_URL, json=payload, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"Error Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_owntracks_webhook()
