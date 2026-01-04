"""Test WABA webhook check with SSL verification disabled."""

import ssl
import httpx
from notebooks.prod_deployment_checker import check_waba_webhook, _print_step

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def main():
    mode = "prod"
    print(f"Checking WABA webhook for {mode} mode (SSL verification disabled)...")
    print("=" * 60)

    try:
        # Monkey patch httpx to disable SSL verification
        import config.waba_setting as waba_setting

        # The pywa client uses httpx internally, we need to configure it
        # Let's try setting an environment variable
        import os
        os.environ['HTTPX_VERIFY_SSL'] = 'false'

        step_ok, step_details = check_waba_webhook(mode)
        _print_step("WABA Webhook Check", step_ok, step_details)

        print("=" * 60)
        if step_ok:
            print("✅ WABA webhook is correctly configured for PROD")
        else:
            print("❌ WABA webhook is NOT configured for PROD")

    except Exception as e:
        print(f"\n❌ Error checking WABA webhook: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
