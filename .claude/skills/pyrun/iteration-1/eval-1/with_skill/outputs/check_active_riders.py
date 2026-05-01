"""
Check active riders in shift for ELAS restaurant.

Standard Imports Section:
- Uses direct Supabase client initialization (fallback pattern)
- Queries rider_master table filtered by town (Salisbury) and is_in_shift=true
- ELAS restaurant is located in Salisbury
"""

import json
from supabase import create_client

# Standard fallback initialization - load credentials from env.json
with open("env.json") as f:
    env = json.load(f)

# Create Supabase client directly (no AWS config module needed)
url = env["sbase_ordelo_rest_url"]
key = env["sbase_ordelo_rest_key"]
client = create_client(url, key)

# Verify ELAS restaurant details
rest_resp = client.table("restaurant_master").select("rest_id, rest_ref, rest_name, city").eq("rest_ref", "ELAS").execute()
if rest_resp.data:
    elas_data = rest_resp.data[0]
    city = elas_data.get("city", "Unknown")
    print(f"Found ELAS restaurant: rest_ref={elas_data['rest_ref']}, rest_name={elas_data['rest_name']}, city={city}")
else:
    print("ELAS restaurant not found")
    exit(1)

# Query rider_master for riders in shift in Salisbury (ELAS town)
riders_resp = client.table("rider_master").select("rider_id, rider_name, vehicle_type, is_in_shift, town, status").eq("town", "Salisbury").eq("is_in_shift", True).execute()

print(f"\nActive riders in shift for Salisbury (ELAS restaurant location): {len(riders_resp.data)}")
print("-" * 80)

if riders_resp.data:
    for rider in riders_resp.data:
        print(f"Rider ID: {rider['rider_id']}")
        print(f"  Name: {rider['rider_name']}")
        print(f"  Vehicle Type: {rider['vehicle_type']}")
        print(f"  Town: {rider['town']}")
        print(f"  Status: {rider['status']}")
        print(f"  In Shift: {rider['is_in_shift']}")
        print()
else:
    print("No active riders in shift for Salisbury")

print(f"\nTotal active riders in shift for ELAS (Salisbury): {len(riders_resp.data)}")
