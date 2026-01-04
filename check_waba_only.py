"""Check WABA webhook configuration only."""

from notebooks.prod_deployment_checker import check_waba_webhook, _print_step

def main():
    mode = "prod"
    print(f"Checking WABA webhook for {mode} mode...")
    print("-" * 50)

    try:
        step_ok, step_details = check_waba_webhook(mode)
        _print_step("WABA Webhook Check", step_ok, step_details)

        if step_ok:
            print("\n✅ WABA webhook is correctly configured for PROD")
        else:
            print("\n❌ WABA webhook is NOT configured for PROD")

    except Exception as e:
        print(f"\n❌ Error checking WABA webhook: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
