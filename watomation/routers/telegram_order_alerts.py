"""
Telegram order-alert ingress for OrdeloAgent (thin route; logic lives in channels/telegram/rest_admin/order_cards).
    . POST /telegram/rest-admin/order-alerts, called every ~5 s (only when there is work) by the PostgreSQL function
      job_t_order_alerts() (ordelo_datamodels/telegram/t_order_alerts.sql) through http_post
    . Body: {"event_type", "timestamp", "reminders": [{order_number, order_type, n, of}], "refreshes": [{order_number, order_type}],
      "receipts": [{order_number, order_type}]}
      (receipts come from job_t_receipt_refresh() in ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql and
      go to Receipts.refresh: the kitchen receipts whose status changed, e.g. after a WhatsApp Ready tap)
    . 503 when the rest-admin bot is not configured: non-2xx keeps the checkpoints pending, so nothing is lost
    . Answers 200 at once and does the Telegram work in background tasks (the SQL job is never held open on Telegram)
    . The database is re-checked before every send (OrderCards), so a replayed or forged call can not send a card for
      an order that is not waiting, and can not show anything the database does not say
    . Like the other SQL-triggered hooks (delivery_hooks.py) this route carries no secret

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
Called by database (SQL triggers / pg_cron jobs POST to these routes):
  . order_alerts(): job_t_order_alerts() in ordelo_datamodels/telegram/t_order_alerts.sql via pg_cron 'job_t_order_alerts' (5 seconds); job_t_receipt_refresh() in ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql via pg_cron 'job_t_receipt_refresh' (5 seconds)
(end of database objects)
"""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from channels.telegram.rest_admin.order_cards import OrderRef
from config.tgram_setting import REST_ADMIN_BOT_KEY

router = APIRouter(tags=["telegram"])


class _Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    order_number: str = Field(min_length=1, max_length=100)
    order_type: Literal["delivery", "takeaway"]


class Reminder(_Order):
    n: int = Field(ge=1)
    of: int = Field(ge=1)


class OrderAlertsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reminders: list[Reminder] = []
    refreshes: list[_Order] = []
    receipts: list[_Order] = []


@router.post("/telegram/rest-admin/order-alerts", include_in_schema=False)
async def order_alerts(payload: OrderAlertsPayload, request: Request, background_tasks: BackgroundTasks):
    """
    Called by database:
      . job_t_order_alerts() in ordelo_datamodels/telegram/t_order_alerts.sql via pg_cron 'job_t_order_alerts' (5 seconds)
      . job_t_receipt_refresh() in ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql via pg_cron 'job_t_receipt_refresh' (5 seconds)
    """
    tg = getattr(request.app.state, "telegram_bots", {}).get(REST_ADMIN_BOT_KEY)
    if tg is None or tg.cards is None:
        raise HTTPException(503, "bot not configured")
    for r in payload.reminders:
        background_tasks.add_task(tg.cards.remind, OrderRef(r.order_number, r.order_type), r.n, r.of)
    for r in payload.refreshes:
        background_tasks.add_task(tg.cards.refresh, OrderRef(r.order_number, r.order_type))
    if tg.receipts is not None:
        for r in payload.receipts:
            background_tasks.add_task(tg.receipts.refresh, OrderRef(r.order_number, r.order_type))
    return {
        "status": "accepted",
        "reminders": len(payload.reminders),
        "refreshes": len(payload.refreshes),
        "receipts": len(payload.receipts) if tg.receipts is not None else 0,
    }
