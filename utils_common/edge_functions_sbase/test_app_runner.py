"""
Test script for the App Runner Manager edge function.
  . Uses requests to send HTTP GET signals to the Deno server
  . Tests both 'pause' and 'resume' actions for a specified service
  Functions/Classes
    . test_pause_service
    . test_resume_service
"""

import requests
import json

# Local Deno server address (default)
BASE_URL = "http://localhost:8000"


def test_pause_service(service_name):
    print(f"Testing PAUSE for {service_name}...")
    url = f"{BASE_URL}/{service_name}/pause"
    try:
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")


def test_resume_service(service_name):
    print(f"\nTesting RESUME for {service_name}...")
    url = f"{BASE_URL}/{service_name}/resume"
    try:
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Change 'ordelo' or 'elaib' to your configured service key
    test_service = "ordelo"
    test_pause_service(test_service)
    test_resume_service(test_service)
