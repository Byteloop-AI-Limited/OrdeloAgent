"""Build the pending rider dashboard cutover in ordelo_datamodels/migrations; never connect or execute.

Run from the prepared Python shell: python scripts/datamodels/rider_dashboard_cutover.py > ordelo_datamodels/migrations/rider_dashboard_cutover.sql
Existing unrelated table/view/function definitions are deliberately not reapplied.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "ordelo_datamodels"


def build() -> str:
    parts = ["""-- MIGRATION (history; do not edit the statements below)
-- Applied to live: not yet (prepared 2026-10-26; owner applies manually; no SQL has been run).
-- Current definitions now live in: admin_dashboard/auth_sessions.sql, admin_dashboard/get_rider_jobs.sql
--   agent_threads/rider_job_history_access.sql, core/rider_master.sql, core/rider_registrations.sql
--   core/ordelo_config.sql, core/restaurant_master.sql, dispatch/delivery_dispatch.sql
--   delivery/delivery_summary.sql, delivery/delivery_detail.sql, dispatch/delivery_inflight.sql
--   ordering/food_order_additions.sql, admin_dashboard/v_admin_orders.sql
--   admin_dashboard/get_rider_payout_report.sql
-- Purpose: Coordinated access-control and rider dashboard RPC cutover. Apply once during the maintenance window
--          before deploying/re-enabling dashboard traffic. This file is the prepared one-time SQL bundle;
--          the owner files above are the ongoing definitions after application.
-- Review and rollout steps: docs/rider-dashboard-rollout.md

-- Rider dashboard: manual coordinated maintenance cutover; not applied.
-- No transaction wrapper; the final statement revokes existing rider dashboard credentials once.
"""]
    parts.append((ROOT / "admin_dashboard/auth_sessions.sql").read_text())
    parts.append((ROOT / "agent_threads/rider_job_history_access.sql").read_text())
    for file, marker in [
        ("core/rider_master.sql", "-- Private dashboard source:"),
        ("core/rider_registrations.sql", "-- Private dashboard source:"),
        ("core/ordelo_config.sql", "-- Dashboard authorization/configuration authority:"),
        ("core/restaurant_master.sql", "-- Dashboard authorization/configuration authority:"),
        ("dispatch/delivery_dispatch.sql", "-- Private dashboard source:"),
        ("delivery/delivery_summary.sql", "-- Private dashboard source:"),
        ("delivery/delivery_detail.sql", "-- Private dashboard source:"),
        ("dispatch/delivery_inflight.sql", "-- Private dashboard source:"),
        ("ordering/food_order_additions.sql", "-- Private order source:"),
        ("admin_dashboard/v_admin_orders.sql", "-- Owner-rights views"),
        ("admin_dashboard/get_rider_payout_report.sql", "-- Banking details"),
    ]:
        text = (ROOT / file).read_text()
        if text.count(marker) != 1:
            raise ValueError(f"expected one cutover marker in {file}")
        parts.append(f"-- From ordelo_datamodels/{file}\n" + text[text.index(marker):])
    parts.append((ROOT / "admin_dashboard/get_rider_jobs.sql").read_text())
    parts.append("""-- Deliberate clean cutover: old pending/active rider credentials are invalidated; no payout changes.
UPDATE public.auth_sessions
SET revoked = true, revoked_at = clock_timestamp(), revoked_reason = 'rider_dashboard_cutover'
WHERE role = 'rider' AND NOT revoked
RETURNING id, role, revoked;
""")
    return "\n\n".join(parts)


if __name__ == "__main__":
    print(build())
