"""Test production deployment checker with SSL verification disabled."""

import ssl
import httpx
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions
from aws_setting import ordelo_agent_env
from notebooks.prod_deployment_checker import (
    check_restaurant_master,
    check_rider_master,
    check_ordelo_app_url,
    _print_step,
)

# Create an SSL context that doesn't verify certificates
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Create httpx client with SSL verification disabled
httpx_client = httpx.Client(verify=False)

# Create Supabase client with custom httpx client
rest_url = ordelo_agent_env.get("sbase_ordelo_rest_url")
rest_key = ordelo_agent_env.get("sbase_ordelo_rest_key")

options = ClientOptions(
    headers={"apikey": rest_key},
    schema="public",
)

client_ordelo = create_client(
    rest_url,
    rest_key,
    options=options,
)

# Monkey patch the client to use our custom httpx client
client_ordelo.postgrest.session = httpx_client

def main():
    mode = "prod"
    print(f"Checking {mode} readiness (SSL verification disabled)...")
    print("=" * 60)

    ok = True

    try:
        step1_ok, step1_details = check_restaurant_master(mode)
        _print_step("Step1 restaurant_master", step1_ok, step1_details)
        ok = ok and step1_ok
    except Exception as e:
        _print_step("Step1 restaurant_master", False, f"Error: {e}")
        ok = False

    try:
        step2_ok, step2_details = check_rider_master(mode)
        _print_step("Step2 rider_master", step2_ok, step2_details)
        ok = ok and step2_ok
    except Exception as e:
        _print_step("Step2 rider_master", False, f"Error: {e}")
        ok = False

    try:
        step3_ok, step3_details = check_ordelo_app_url(mode)
        _print_step("Step3 ordelo_config", step3_ok, step3_details)
        ok = ok and step3_ok
    except Exception as e:
        _print_step("Step3 ordelo_config", False, f"Error: {e}")
        ok = False

    print("=" * 60)
    if ok:
        print("✅ Checklist status: READY")
    else:
        print("❌ Checklist status: NOT READY")

    return ok

if __name__ == "__main__":
    # Inject our custom client into the config module
    import config
    config.client_ordelo = client_ordelo

    main()
