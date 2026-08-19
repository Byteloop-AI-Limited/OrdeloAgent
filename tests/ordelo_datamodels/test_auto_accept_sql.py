"""Static contracts for configured restaurant auto-accept SQL sources."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_canonical_sql_installs_auto_accept_schema_policy_and_takeaway_insert_trigger() -> None:
    masterdata = _read("ordelo_datamodels/masterdata.sql")
    delivery_summary = _read("ordelo_datamodels/summary.sql")
    resolver = _read(
        "ordelo_datamodels/jobs_n_functions/resolve_initial_restaurant_acceptance.sql"
    )
    takeaway_summary = _read("ordelo_datamodels/takeaway_summary.sql")

    assert "auto_accept BOOLEAN NOT NULL DEFAULT FALSE" in masterdata
    assert "rest_confirmation_method IS NULL" in delivery_summary
    assert "'manual', 'timeout', 'configured_auto'" in delivery_summary
    assert "CREATE OR REPLACE FUNCTION public.resolve_initial_restaurant_acceptance" in resolver
    assert "trigger_takeaway_pickup_time_insert" in takeaway_summary


def test_initializers_map_configured_auto_to_dispatch_ready_states() -> None:
    delivery = _read("ordelo_datamodels/jobs_n_functions/init_delivery.sql")
    takeaway = _read("ordelo_datamodels/jobs_n_functions/init_takeaway.sql")

    assert "resolve_initial_restaurant_acceptance" in delivery
    assert "CASE WHEN v_auto_accept THEN 'unassigned' ELSE 'restaurant_unconfirmed' END" in delivery
    assert "CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END" in delivery
    assert "resolve_initial_restaurant_acceptance" in takeaway
    assert "CASE WHEN v_auto_accept THEN 'pickup_confirmed' ELSE 'restaurant_unconfirmed' END" in takeaway
    assert "CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END" in takeaway


def test_initializers_qualify_acceptance_result_columns() -> None:
    qualified_select = (
        "acceptance.auto_accept,\n"
        "        acceptance.pickup_minutes,\n"
        "        acceptance.pickup_time"
    )
    for relative_path in (
        "ordelo_datamodels/jobs_n_functions/init_delivery.sql",
        "ordelo_datamodels/jobs_n_functions/init_takeaway.sql",
    ):
        initializer = _read(relative_path)
        assert qualified_select in initializer
        assert ") AS acceptance;" in initializer


def test_acceptance_policy_uses_restaurant_config_before_global_fallback() -> None:
    resolver = _read(
        "ordelo_datamodels/jobs_n_functions/resolve_initial_restaurant_acceptance.sql"
    )

    assert "'_DEFAULT_DELIVERY_PICKUP_TIME'" in resolver
    assert "'DEFAULT_DELIVERY_PICKUP_TIME'" in resolver
    assert "'_DEFAULT_COLLECTION_PICKUP_TIME'" in resolver
    assert "'DEFAULT_COLLECTION_PICKUP_TIME'" in resolver
    assert "'^[1-9][0-9]*$'" in resolver
    assert "Auto-accept pickup configuration is missing or invalid" in resolver


def test_takeaway_pickup_trigger_supports_auto_accept_insert() -> None:
    takeaway_summary = _read("ordelo_datamodels/takeaway_summary.sql")

    assert "AFTER INSERT ON public.takeaway_summary" in takeaway_summary
    assert "WHEN (NEW.pickup_time IS NOT NULL)" in takeaway_summary
    assert "EXECUTE FUNCTION takeaway_pickup_time_whook();" in takeaway_summary
