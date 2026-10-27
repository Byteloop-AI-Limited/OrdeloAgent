"""
Rider offer reminder ingress (thin route; logic in ordelo/offer_reminders.py).
    . POST /rider-hooks/offer-alerts, called every ~5 s (only when something is due) by job_rider_offer_alerts()
      (ordelo_datamodels/dispatch/job_rider_offer_alerts.sql) through http_post
    . Body: {"event_type", "timestamp", "reminders": [{dispatch_id, n, of}], "escalations": [{order_number, after_secs, offered, declined, redispatched}]}
    . 503 when the rider bot is not configured: non-2xx keeps the checkpoints pending, so nothing is lost
    . Answers 200 at once and does the Telegram work in background tasks
    . The database is re-checked before every send (rider_offer_reminder_snapshot), so a replayed or forged call cannot
      remind an offer that is not open; like the other SQL-triggered hooks this route carries no secret

Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . offer_alerts(): job_rider_offer_alerts() in ordelo_datamodels/dispatch/job_rider_offer_alerts.sql via pg_cron 'job_rider_offer_alerts' (5 seconds)
(end of database objects)
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ordelo import offer_reminders

router = APIRouter(tags=["rider-hooks"])


class Reminder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dispatch_id: int = Field(ge=1)
    n: int = Field(ge=1)
    of: int = Field(ge=1)


class Escalation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_number: str = Field(min_length=1, max_length=100)
    after_secs: int = Field(ge=1)
    offered: int = Field(default=0, ge=0)
    declined: int = Field(default=0, ge=0)
    redispatched: bool = False


class OfferAlertsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reminders: list[Reminder] = []
    escalations: list[Escalation] = []


@router.post("/rider-hooks/offer-alerts", include_in_schema=False)
async def offer_alerts(payload: OfferAlertsPayload, background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_rider_offer_alerts() in ordelo_datamodels/dispatch/job_rider_offer_alerts.sql via pg_cron 'job_rider_offer_alerts' (5 seconds)
    """
    from config import rider_bot

    if rider_bot is None:
        raise HTTPException(503, "rider bot not configured")
    for r in payload.reminders:
        background_tasks.add_task(offer_reminders.remind, r.dispatch_id, r.n, r.of)
    for e in payload.escalations:
        background_tasks.add_task(offer_reminders.escalate, e.order_number, e.after_secs, e.offered, e.declined, e.redispatched)
    return {"status": "accepted", "reminders": len(payload.reminders), "escalations": len(payload.escalations)}
