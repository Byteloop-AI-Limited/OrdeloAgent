"""Deployment checklist + mode switcher for Ordelo.

This script checks the configured test/prod state and optionally applies updates
using the Supabase client and WABA settings.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Tuple

from config import client_ordelo
from config import waba_setting

RESTAURANT_UPDATES: Dict[str, Dict[str, Any]] = {
    "prod": {
        "admins": [
            "447448440754",
            "447446933210",
            "447901518136",
            "447914844933",
            "447917912646",
        ],
        "rest_stale_active_threads_minutes": 10,
        "restaurant_start_time": 12,
        "restaurant_end_time": 21.30,
    },
    "test": {
        "admins": ["447919202938"],
        "rest_stale_active_threads_minutes": 10,
        "restaurant_start_time": 11,
        "restaurant_end_time": 21.30,
    },
}

ORDELO_APP_URLS = {
    "test": "https://rider-agent-test.ordelo.app",
    "prod": "https://rider-agent.ordelo.app",
}

WABA_CALLBACK_URLS = {
    "test": "https://rider-agent-test.ordelo.app/",
    "prod": "https://rider-agent.ordelo.app/",
}

RIDER_TARGET_TOWN = "Salisbury"
RIDER_DUMMY_TOWN = "dummy"
RIDER_EXCLUDED_NAME = "Lohith"
CACHE_RESET_REFS = ("elas", "ordelo")


def _normalize_admins(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return sorted(str(item) for item in value)
    text_value = str(value).strip().strip("{}")
    return sorted(item.strip() for item in text_value.split(",") if item.strip())


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_equal(left: Any, right: Any, tol: float = 1e-6) -> bool:
    left_num = _as_float(left)
    right_num = _as_float(right)
    if left_num is None or right_num is None:
        return False
    return abs(left_num - right_num) <= tol


def _normalize_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.rstrip("/")


def _extract_waba_callback_url(webhook_config: Any) -> Optional[str]:
    if webhook_config is None:
        return None
    if isinstance(webhook_config, dict):
        value = webhook_config.get("whatsapp_business_account")
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return str(value[1])
        if isinstance(value, dict):
            return value.get("callback_url") or value.get("url")
        if isinstance(value, str):
            return value
        return webhook_config.get("callback_url") or webhook_config.get("url")
    return None


def _print_step(step_name: str, ok: bool, details: str) -> None:
    status = "OK" if ok else "MISMATCH"
    print(f"{step_name}: {status}")
    if details:
        print(f"  {details}")


def _get_single_row(table: str, columns: str, key: str, value: str) -> Dict[str, Any]:
    res = client_ordelo.table(table).select(columns).eq(key, value).execute()
    return (res.data or [{}])[0]


def check_restaurant_master(mode: str) -> Tuple[bool, str]:
    expected = RESTAURANT_UPDATES[mode]
    row = _get_single_row(
        "restaurant_master",
        "admins, rest_stale_active_threads_minutes, restaurant_start_time, restaurant_end_time",
        "rest_ref",
        "ELAS",
    )

    admins_ok = _normalize_admins(row.get("admins")) == _normalize_admins(
        expected["admins"]
    )
    stale_ok = (
        row.get("rest_stale_active_threads_minutes")
        == expected["rest_stale_active_threads_minutes"]
    )
    start_ok = _float_equal(
        row.get("restaurant_start_time"), expected["restaurant_start_time"]
    )
    end_ok = _float_equal(
        row.get("restaurant_end_time"), expected["restaurant_end_time"]
    )

    ok = all([admins_ok, stale_ok, start_ok, end_ok])
    details = (
        f"admins_ok={admins_ok}, stale_ok={stale_ok}, "
        f"start_ok={start_ok}, end_ok={end_ok}"
    )
    return ok, details


def apply_restaurant_master(mode: str) -> None:
    payload = RESTAURANT_UPDATES[mode]
    client_ordelo.table("restaurant_master").update(payload).eq(
        "rest_ref", "ELAS"
    ).execute()


def check_rider_master(mode: str) -> Tuple[bool, str]:
    dummy_rows = (
        client_ordelo.table("rider_master")
        .select("rider_id")
        .eq("town", RIDER_DUMMY_TOWN)
        .execute()
        .data
        or []
    )
    salisbury_rows = (
        client_ordelo.table("rider_master")
        .select("rider_id")
        .eq("town", RIDER_TARGET_TOWN)
        .neq("rider_name", RIDER_EXCLUDED_NAME)
        .execute()
        .data
        or []
    )

    if mode == "test":
        ok = len(salisbury_rows) == 0
    else:
        ok = len(dummy_rows) == 0

    details = (
        f"salisbury_excl_{RIDER_EXCLUDED_NAME.lower()}_count={len(salisbury_rows)}, "
        f"dummy_count={len(dummy_rows)}"
    )
    return ok, details


def apply_rider_master(mode: str) -> None:
    if mode == "test":
        client_ordelo.table("rider_master").update({"town": RIDER_DUMMY_TOWN}).eq(
            "town", RIDER_TARGET_TOWN
        ).neq("rider_name", RIDER_EXCLUDED_NAME).execute()
    else:
        client_ordelo.table("rider_master").update({"town": RIDER_TARGET_TOWN}).eq(
            "town", RIDER_DUMMY_TOWN
        ).execute()


def check_ordelo_app_url(mode: str) -> Tuple[bool, str]:
    row = _get_single_row(
        "ordelo_config", "config_value", "config_key", "ORDELO_APP_URL"
    )
    current = row.get("config_value")
    expected = ORDELO_APP_URLS[mode]
    ok = current == expected
    details = f"current={current}, expected={expected}"
    return ok, details


def apply_ordelo_app_url(mode: str) -> None:
    client_ordelo.table("ordelo_config").update(
        {"config_value": ORDELO_APP_URLS[mode]}
    ).eq("config_key", "ORDELO_APP_URL").execute()


def check_waba_webhook(mode: str) -> Tuple[bool, str]:
    business_phone_number = waba_setting._sync_wa_client.get_business_phone_number()
    webhook_config = getattr(business_phone_number, "webhook_configuration", None)
    current_url = _extract_waba_callback_url(webhook_config)
    expected_url = WABA_CALLBACK_URLS[mode]

    ok = _normalize_url(current_url) == _normalize_url(expected_url)
    details = f"current={current_url}, expected={expected_url}"
    return ok, details


def apply_waba_webhook(mode: str) -> None:
    callback_url = WABA_CALLBACK_URLS[mode]
    verify_token = waba_setting.waba_business_settings.verify_token or "123456"
    waba_setting._sync_wa_client.override_waba_callback_url(
        callback_url=callback_url,
        verify_token=verify_token,
        waba_id=waba_setting.waba_business_settings.account_id,
    )


def reset_restaurant_base_url_cache() -> None:
    import requests

    base_url = "https://rider-agent.ordelo.app"
    for rest_ref in CACHE_RESET_REFS:
        url = f"{base_url}/restaurant-base-url-cache/reset"
        try:
            response = requests.post(
                url,
                params={"rest_ref": rest_ref},
                headers={"accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Cache reset failed for {rest_ref}: {exc}")
        else:
            print(f"Cache reset OK for {rest_ref}")


def run_check(mode: str, skip_waba: bool) -> bool:
    ok = True

    step1_ok, step1_details = check_restaurant_master(mode)
    _print_step("Step1 restaurant_master", step1_ok, step1_details)
    ok = ok and step1_ok

    step2_ok, step2_details = check_rider_master(mode)
    _print_step("Step2 rider_master", step2_ok, step2_details)
    ok = ok and step2_ok

    step3_ok, step3_details = check_ordelo_app_url(mode)
    _print_step("Step3 ordelo_config", step3_ok, step3_details)
    ok = ok and step3_ok

    if skip_waba:
        _print_step("Step4 waba webhook", True, "skipped")
    else:
        step4_ok, step4_details = check_waba_webhook(mode)
        _print_step("Step4 waba webhook", step4_ok, step4_details)
        ok = ok and step4_ok

    return ok


def run_apply(mode: str, skip_waba: bool) -> None:
    apply_restaurant_master(mode)
    apply_rider_master(mode)
    apply_ordelo_app_url(mode)
    if not skip_waba:
        apply_waba_webhook(mode)
    reset_restaurant_base_url_cache()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check readiness for prod/test and optionally apply updates."
    )
    parser.add_argument("--mode", required=True, choices=["test", "prod"])
    parser.add_argument(
        "--apply", action="store_true", help="Apply updates before checking"
    )
    parser.add_argument(
        "--skip-waba", action="store_true", help="Skip WABA webhook check/update"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.apply:
        print(f"Applying {args.mode} updates...")
        run_apply(args.mode, args.skip_waba)

    print(f"Checking {args.mode} readiness...")
    all_ok = run_check(args.mode, args.skip_waba)

    if all_ok:
        print("Checklist status: READY")
    else:
        print("Checklist status: NOT READY")


if __name__ == "__main__":
    main()

"""
python notebooks/prod_deployment_checker.py --mode test
python notebooks/prod_deployment_checker.py --mode prod

"""
