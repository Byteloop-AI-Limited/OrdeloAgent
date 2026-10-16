"""Static contracts for configured restaurant auto-accept SQL sources.

The SQL files are formatted by pg_format and table DDL is generated from the live catalogue, so these checks compare
text with case and whitespace removed (``_squash``) instead of relying on one layout.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _squash(text: str) -> str:
    """Lower-case, no whitespace, no ``public.`` qualifier: layout-independent SQL text."""
    return re.sub(r"\s+", "", text.lower()).replace("public.", "")


def _has(needle: str, haystack: str) -> bool:
    return _squash(needle) in _squash(haystack)


def test_canonical_sql_installs_auto_accept_schema_policy_and_takeaway_insert_trigger() -> None:
    masterdata = _read("ordelo_datamodels/core/restaurant_master.sql")
    delivery_summary = _read("ordelo_datamodels/delivery/delivery_summary.sql")
    resolver = _read(
        "ordelo_datamodels/restaurant_admin/resolve_initial_restaurant_acceptance.sql"
    )
    takeaway_summary = _read("ordelo_datamodels/takeaway/takeaway_summary.sql")

    assert _has("auto_accept boolean NOT NULL DEFAULT false", masterdata)
    assert _has("rest_confirmation_method IS NULL", delivery_summary)
    assert all(_has(f"'{m}'", delivery_summary) for m in ("manual", "timeout", "configured_auto"))
    assert _has("CREATE OR REPLACE FUNCTION public.resolve_initial_restaurant_acceptance", resolver)
    assert "trigger_takeaway_pickup_time_insert" in takeaway_summary


def test_initializers_map_configured_auto_to_dispatch_ready_states() -> None:
    delivery = _read("ordelo_datamodels/delivery/init_delivery.sql")
    takeaway = _read("ordelo_datamodels/takeaway/init_takeaway.sql")

    assert "resolve_initial_restaurant_acceptance" in delivery
    assert _has("CASE WHEN v_auto_accept THEN 'unassigned' ELSE 'restaurant_unconfirmed' END", delivery)
    assert _has("CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END", delivery)
    assert "resolve_initial_restaurant_acceptance" in takeaway
    assert _has("CASE WHEN v_auto_accept THEN 'pickup_confirmed' ELSE 'restaurant_unconfirmed' END", takeaway)
    assert _has("CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END", takeaway)


def test_initializers_qualify_acceptance_result_columns() -> None:
    qualified_select = (
        "acceptance.auto_accept,\n"
        "        acceptance.pickup_minutes,\n"
        "        acceptance.pickup_time"
    )
    for relative_path in (
        "ordelo_datamodels/delivery/init_delivery.sql",
        "ordelo_datamodels/takeaway/init_takeaway.sql",
    ):
        initializer = _read(relative_path)
        assert _has(qualified_select, initializer)
        assert _has(") AS acceptance;", initializer)


def test_acceptance_policy_uses_restaurant_config_before_global_fallback() -> None:
    resolver = _read(
        "ordelo_datamodels/restaurant_admin/resolve_initial_restaurant_acceptance.sql"
    )

    assert "'_DEFAULT_DELIVERY_PICKUP_TIME'" in resolver
    assert "'DEFAULT_DELIVERY_PICKUP_TIME'" in resolver
    assert "'_DEFAULT_COLLECTION_PICKUP_TIME'" in resolver
    assert "'DEFAULT_COLLECTION_PICKUP_TIME'" in resolver
    assert "'^[1-9][0-9]*$'" in resolver
    assert "Auto-accept pickup configuration is missing or invalid" in resolver


def test_takeaway_pickup_trigger_supports_auto_accept_insert() -> None:
    takeaway_summary = _read("ordelo_datamodels/takeaway/takeaway_summary.sql")

    assert _has("AFTER INSERT ON public.takeaway_summary", takeaway_summary)
    assert _has("WHEN (NEW.pickup_time IS NOT NULL)", takeaway_summary)
    assert _has("EXECUTE FUNCTION takeaway_pickup_time_whook();", takeaway_summary)
