"""Query riders in shift with SSL verification disabled for sandbox environments."""

import os
import httpx
from supabase import create_client
from aws_setting import ordelo_agent_env
from collections import defaultdict
from datetime import datetime

# Set up NO_PROXY
os.environ['NO_PROXY'] = os.environ.get('NO_PROXY', '') + ',*.amazonaws.com,*.supabase.co,*.supabase.com'
os.environ['no_proxy'] = os.environ.get('no_proxy', '') + ',*.amazonaws.com,*.supabase.co,*.supabase.com'

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Create Supabase client
rest_url = ordelo_agent_env.get("sbase_ordelo_rest_url")
rest_key = ordelo_agent_env.get("sbase_ordelo_rest_key")

client_ordelo = create_client(rest_url, rest_key)

# Monkey patch with SSL disabled httpx client (needed for sandbox/proxy environments)
postgrest_url = f"{rest_url}/rest/v1"
headers = {
    "apikey": rest_key,
    "Authorization": f"Bearer {rest_key}",
}
httpx_client = httpx.Client(verify=False, base_url=postgrest_url, headers=headers)
client_ordelo.postgrest.session = httpx_client

# Query riders in shift
res = (
    client_ordelo.table("rider_master")
    .select("*")
    .eq("is_in_shift", True)
    .eq("status", "active")
    .order("shift_response_dtts", desc=True)
    .limit(100)
    .execute()
)

riders = res.data

print(f"\n{'='*70}")
print(f"RIDERS IN SHIFT TODAY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*70}\n")

if not riders:
    print("❌ No riders are currently in shift.\n")
else:
    print(f"✅ {len(riders)} active riders in shift:\n")

    for i, rider in enumerate(riders, 1):
        print(f"{i}. {rider.get('rider_name', 'Unknown'):15} | {rider.get('vehicle_type', 'N/A'):15} | {rider.get('town', 'N/A')}")
        print(f"   ID: {rider.get('rider_id', 'N/A'):15} | Priority: {rider.get('priority', 'N/A')}")
        shift_response = rider.get('shift_response_dtts', 'Not recorded')
        print(f"   Last Shift Response: {shift_response}")
        print()

print(f"{'='*70}")
print(f"Total: {len(riders)} riders in shift")
print(f"{'='*70}\n")

# Group by vehicle type
by_vehicle = defaultdict(list)
for rider in riders:
    vehicle = rider.get('vehicle_type', 'unknown')
    name = rider.get('rider_name', 'Unknown')
    by_vehicle[vehicle].append(name)

print("\n📊 Breakdown by Vehicle Type:")
print("-" * 40)
for vehicle, names in sorted(by_vehicle.items()):
    print(f"\n{vehicle.upper()}: {len(names)} rider(s)")
    for name in names:
        print(f"  • {name}")

# Group by town
by_town = defaultdict(list)
for rider in riders:
    town = rider.get('town', 'unknown')
    name = rider.get('rider_name', 'Unknown')
    by_town[town].append(name)

print(f"\n\n📍 Breakdown by Town:")
print("-" * 40)
for town, names in sorted(by_town.items()):
    print(f"\n{town}: {len(names)} rider(s)")
    for name in names:
        print(f"  • {name}")

print("\n")
