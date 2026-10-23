"""
Pause-sweep ingress for OrdeloAgent (thin route; texts and routing live in ordelo/pause_notices.py). Phase R5-R6 of
plans/telegram-rider-bot-plan.md, ADR 0013.
    . POST /pause-hooks/sweep, called every minute (only when there is something to say) by the PostgreSQL function
      job_pause_sweep() (ordelo_datamodels/availability/job_pause_sweep.sql) through http_post
    . Body: {"event_type": "pause_sweep", "ending_soon": [item], "ended": [item]},
      item = {pause_id, audience: 'rider' | 'rest_admin', principal (phone), scope (rest_ref for an admin), ends_at}
    . Answers 200 at once and sends in background tasks (the SQL job is never held open on Telegram or WhatsApp); the job
      marks reminded_at / announced_at on the 2xx, so a send that fails afterwards is logged, not retried
    . The messages change nothing: availability is computed from the clock (is_paused), so a replayed or forged call can
      only repeat a notice, never switch anyone on or off
    . Like the other SQL-triggered hooks (delivery_hooks.py, telegram_order_alerts.py) this route carries no secret

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . pause_sweep(): job_pause_sweep() in ordelo_datamodels/availability/job_pause_sweep.sql via pg_cron 'job_pause_sweep' (* * * * *)
(end of database objects)
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from config.tgram_setting import REST_ADMIN_BOT_KEY
from ordelo import pause_notices

router = APIRouter(tags=["pauses"])


class PauseItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pause_id: int
    audience: Literal["rider", "rest_admin"]
    principal: str = Field(min_length=8, max_length=15)
    scope: str | None = None
    ends_at: datetime


class PauseSweepPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ending_soon: list[PauseItem] = []
    ended: list[PauseItem] = []


@router.post("/pause-hooks/sweep", include_in_schema=False)
async def pause_sweep(payload: PauseSweepPayload, request: Request, background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_pause_sweep() in ordelo_datamodels/availability/job_pause_sweep.sql via pg_cron 'job_pause_sweep' (* * * * *)
    """
    tg = getattr(request.app.state, "telegram_bots", {}).get(REST_ADMIN_BOT_KEY)
    bot = getattr(tg, "bot", None)
    for kind, items in ((pause_notices.ENDING_SOON, payload.ending_soon), (pause_notices.ENDED, payload.ended)):
        for item in items:
            if item.audience == "rider":
                background_tasks.add_task(pause_notices.tell_rider, item.principal, kind, item.ends_at)
            elif item.scope:
                background_tasks.add_task(pause_notices.tell_admin, bot, REST_ADMIN_BOT_KEY, item.principal, item.scope,
                                          kind, item.ends_at)
    return {"status": "accepted", "ending_soon": len(payload.ending_soon), "ended": len(payload.ended)}
