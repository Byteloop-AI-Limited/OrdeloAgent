"""
Switch ELAS (and CHKS) between test and production environments.

Usage:
    PYTHONPATH=$REPO_ROOT /usr/bin/python3.13 references/switch_elas_test_prod.py --mode test
    PYTHONPATH=$REPO_ROOT /usr/bin/python3.13 references/switch_elas_test_prod.py --mode prod
"""
import argparse
from config import client_ordelo

TEST_CONFIG = {
    "restaurant_master": {
        "admins": ["447919202938"],
        "rest_stale_active_threads_minutes": 10,
        "restaurant_start_time": 11,
        "restaurant_end_time": 21.30,
        "city": "dummy",
    },
    "rider_master": {
        "is_in_shift": True,
        "town": "dummy",
        "vehicle_type": "bicycle",
    },
}

PROD_CONFIG = {
    "restaurant_master": {
        "admins": ["447448440754", "447446933210", "447901518136", "447914844933", "447917912646", "447909488602"],
        "rest_stale_active_threads_minutes": 10,
        "restaurant_start_time": 12,
        "restaurant_end_time": 21.30,
        "city": "Salisbury",
    },
    "rider_master": {
        "is_in_shift": True,
        "town": "Salisbury",
        "vehicle_type": "bicycle",
    },
}


def verify():
    resp = client_ordelo.table("restaurant_master").select(
        "rest_ref, admins, city, restaurant_start_time, restaurant_end_time, rest_stale_active_threads_minutes"
    ).in_("rest_ref", ["ELAS", "CHKS"]).execute()
    print("restaurant_master:", resp.data)

    resp2 = client_ordelo.table("rider_master").select(
        "rider_name, is_in_shift, town, vehicle_type"
    ).eq("rider_name", "Lohith").execute()
    print("rider_master:", resp2.data)


def switch(mode: str):
    config = TEST_CONFIG if mode == "test" else PROD_CONFIG

    print(f"\n--- BEFORE ({mode}) ---")
    verify()

    client_ordelo.table("restaurant_master").update(
        config["restaurant_master"]
    ).in_("rest_ref", ["ELAS", "CHKS"]).execute()

    client_ordelo.table("rider_master").update(
        config["rider_master"]
    ).eq("rider_name", "Lohith").execute()

    print(f"\n--- AFTER ({mode}) ---")
    verify()
    print(f"\nSwitched ELAS/CHKS to {mode.upper()} mode.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Switch ELAS/CHKS between test and prod")
    parser.add_argument("--mode", choices=["test", "prod"], required=True)
    args = parser.parse_args()
    switch(args.mode)
