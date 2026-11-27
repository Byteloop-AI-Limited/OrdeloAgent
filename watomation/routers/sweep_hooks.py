"""
Thin hooks woken by pg_cron (ADR 0019: Postgres owns every schedule; FastAPI never polls).
    . Each route answers 200 at once and runs one existing sweep in BackgroundTasks. The body is ignored.
    . The sweeps claim their rows in SQL (leases, SKIP LOCKED, per-day claims), so a replayed or forged call only
      runs a sweep early. Like the other SQL-triggered hooks these routes carry no secret.
    . Not under /web: that router requires the storefront key, which pg_cron does not send.
  Routes:
    . POST /rider-hooks/invite-alerts   -> channels/telegram/rider/invite_alerts.sweep_pending()
    . POST /customer-hooks/outbox-sweep -> utils_common/notify/customer_notifier.sweep_pending()
    . POST /web-hooks/lifecycle-sweep   -> utils_common/web_ordering/lifecycle.sweep()   (WEB expiry, prunes, payment release)
    . POST /web-hooks/price-audit       -> utils_common/web_ordering/monitoring.sweep()  (one claim per London day)
    . Each route runs its sweep in its own background task, so one failing sweep never skips another (the old
      in-process loop ran the three customer sweeps in one try block).

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . rider_invite_alerts(): job_rider_invite_alerts() in ordelo_datamodels/telegram/job_rider_invite_alerts.sql via pg_cron 'job_rider_invite_alerts' (* * * * *)
  . customer_outbox_sweep(): job_customer_outbox_sweep() in ordelo_datamodels/notifications/job_customer_outbox_sweep.sql via pg_cron 'job_customer_outbox_sweep' (* * * * *)
  . web_lifecycle_sweep(): job_web_lifecycle_sweep() in ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql via pg_cron 'job_web_lifecycle_sweep' (* * * * *)
  . web_price_audit(): job_web_price_audit() in ordelo_datamodels/ordering/job_web_price_audit.sql via pg_cron 'job_web_price_audit' (5 * * * *, POSTs only when today's London audit is due)
(end of database objects)
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks
from loguru import logger

router = APIRouter(tags=["sweep-hooks"])


async def _run(name: str, sweep: Callable[[], Awaitable[object]]) -> None:
    try:
        result = await sweep()
        logger.info("sweep[{}]: done result={}", name, result)
    except Exception as exc:  # a failed sweep must not crash the worker; the next cron tick retries
        # Only the class: exception text may carry request arguments, and an invite code must never reach a log.
        logger.error("sweep[{}]: failed error_type={}", name, type(exc).__name__)


@router.post("/rider-hooks/invite-alerts", include_in_schema=False)
async def rider_invite_alerts(background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_rider_invite_alerts() in ordelo_datamodels/telegram/job_rider_invite_alerts.sql via pg_cron 'job_rider_invite_alerts' (* * * * *)
    """
    from channels.telegram.rider.invite_alerts import sweep_pending

    background_tasks.add_task(_run, "rider_invite_alerts", sweep_pending)
    return {"status": "accepted"}


@router.post("/customer-hooks/outbox-sweep", include_in_schema=False)
async def customer_outbox_sweep(background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_customer_outbox_sweep() in ordelo_datamodels/notifications/job_customer_outbox_sweep.sql via pg_cron 'job_customer_outbox_sweep' (* * * * *)
    """
    from utils_common.notify.customer_notifier import sweep_pending

    background_tasks.add_task(_run, "customer_outbox_sweep", sweep_pending)
    return {"status": "accepted"}


@router.post("/web-hooks/lifecycle-sweep", include_in_schema=False)
async def web_lifecycle_sweep(background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_web_lifecycle_sweep() in ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql via pg_cron 'job_web_lifecycle_sweep' (* * * * *)
    """
    from utils_common.web_ordering.lifecycle import sweep

    background_tasks.add_task(_run, "web_lifecycle_sweep", sweep)
    return {"status": "accepted"}


@router.post("/web-hooks/price-audit", include_in_schema=False)
async def web_price_audit(background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_web_price_audit() in ordelo_datamodels/ordering/job_web_price_audit.sql via pg_cron 'job_web_price_audit' (5 * * * *, POSTs only when today's London audit is due)
    """
    from utils_common.web_ordering.monitoring import sweep

    background_tasks.add_task(_run, "web_price_audit", sweep)
    return {"status": "accepted"}
