#!/usr/bin/env python
"""
Query active riders for ELAS restaurant from rider_master table.
Checks for riders with is_in_shift=true assigned to ELAS restaurant.

This script queries the Ordelo Supabase database directly without using
any helper skills or utilities to demonstrate baseline functionality.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to sys.path so we can import config modules
project_root = Path("/home/basal/bloop/OrdeloAgent")
sys.path.insert(0, str(project_root))

# Set the working directory for config loading
os.chdir(project_root)

# Load environment variables from .env files
env_file = project_root / ".env_ssm"
if env_file.exists():
    load_dotenv(env_file)

# ============================================================================
# QUERY ACTIVE RIDERS FOR ELAS RESTAURANT
# ============================================================================

from config import client_ordelo

def get_active_riders_for_restaurant(rest_ref: str):
    """
    Query rider_master table for active riders in shift for a specific restaurant.

    Note: rider_master table does not have a direct restaurant reference.
    This query returns ALL riders currently in shift (is_in_shift=true)
    across all restaurants. The assumption is that riders work for specific
    restaurants based on their assigned town/location.

    Args:
        rest_ref: Restaurant reference (e.g., 'ELAS')

    Returns:
        dict with:
            - count: number of active riders
            - riders: list of rider names
            - details: full rider records
    """

    # First, get restaurant info to understand its context
    rest_resp = (
        client_ordelo.table("restaurant_master")
        .select("rest_ref, rest_name, city")
        .eq("rest_ref", rest_ref.upper())
        .execute()
    )

    rest_data = rest_resp.data if hasattr(rest_resp, 'data') else rest_resp.get('data', [])

    if not rest_data:
        return {
            "status": "error",
            "message": f"Restaurant {rest_ref} not found",
            "count": 0,
            "riders": [],
            "details": []
        }

    restaurant = rest_data[0]
    rest_city = restaurant.get('city', 'Unknown')
    rest_name = restaurant.get('rest_name', 'Unknown')

    # Query riders in shift (is_in_shift = true)
    # Since rider_master doesn't have a direct rest_ref, we query by city/town
    riders_resp = (
        client_ordelo.table("rider_master")
        .select("id, rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority, dtts, shift_response_dtts")
        .eq("is_in_shift", True)
        .eq("town", rest_city)
        .order("shift_response_dtts", desc=True)
        .execute()
    )

    riders_data = riders_resp.data if hasattr(riders_resp, 'data') else riders_resp.get('data', [])

    # Extract rider names and build detailed info
    rider_names = [rider.get('rider_name', 'Unknown') for rider in riders_data]

    result = {
        "status": "success",
        "restaurant": {
            "rest_ref": rest_ref.upper(),
            "rest_name": rest_name,
            "city": rest_city
        },
        "count": len(riders_data),
        "riders": rider_names,
        "details": riders_data
    }

    return result


def main():
    """Main execution function"""
    print("=" * 80)
    print("ACTIVE RIDERS QUERY FOR ELAS RESTAURANT")
    print("=" * 80)
    print()

    rest_ref = "ELAS"

    try:
        result = get_active_riders_for_restaurant(rest_ref)

        if result["status"] == "success":
            restaurant = result["restaurant"]
            print(f"Restaurant: {restaurant['rest_name']} ({restaurant['rest_ref']})")
            print(f"City: {restaurant['city']}")
            print()
            print(f"Active Riders in Shift: {result['count']}")
            print("-" * 80)

            if result['riders']:
                for i, rider in enumerate(result['details'], 1):
                    print(f"\n{i}. {rider.get('rider_name', 'N/A')}")
                    print(f"   Rider ID: {rider.get('rider_id', 'N/A')}")
                    print(f"   Vehicle: {rider.get('vehicle_type', 'N/A')}")
                    print(f"   Town: {rider.get('town', 'N/A')}")
                    print(f"   Status: {rider.get('status', 'N/A')}")
                    print(f"   In Shift: {rider.get('is_in_shift', False)}")
                    print(f"   Priority: {rider.get('priority', 'N/A')}")
                    print(f"   Shift Response Time: {rider.get('shift_response_dtts', 'N/A')}")
            else:
                print("\nNo active riders currently in shift for this restaurant.")
        else:
            print(f"Error: {result['message']}")

        return result

    except Exception as e:
        print(f"Error occurred: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
            "count": 0,
            "riders": [],
            "details": []
        }


if __name__ == "__main__":
    result = main()

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Restaurant: {result.get('restaurant', {}).get('rest_ref', 'N/A')}")
    print(f"Active Riders Count: {result.get('count', 0)}")
    print(f"Rider Names: {', '.join(result.get('riders', [])) if result.get('riders') else 'None'}")
