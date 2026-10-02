"""Web-only late-payment release and abandoned checkout maintenance.

The late-authorisation decision and release intent commit before replying to
Stripe; the sweep recovers crashes. This never initializes a rejected order.
Retries here apply to payment cancellation, not restaurant-app notifications.
"""
import asyncio
from datetime import timedelta
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from config.feature_flags import flag_enabled
from config.pg_setting import pg_settings
from loguru import logger
from utils_common.notify import customer_notifier
from utils_common.notify.customer_notifier import CustomerOrderEvent
from .common import one, query, utcnow
from .availability import available
from .common import WebError

async def reject_late(evt):
    if evt is None or not await flag_enabled('WEB_LATE_PAYMENT_GUARD_ENABLED'):
        return None
    order = await one('SELECT * FROM food_order WHERE order_id=%s', (evt.order_id,))
    if not order or order.get('origin_channel') != 'web':
        return None
    if await one('SELECT 1 FROM web_payment_release WHERE order_number=%s', (order['order_number'],)):
        return 'late_rejected_duplicate'
    late = utcnow() > order['order_dtts']+timedelta(minutes=35)
    if not late:
        try:
            await available(order['order_number'].split('-')[0], 'delivery' if order['action']=='delivery' else 'collection', new_order=False)
        except WebError as exc:
            # A transient DB/pricing/config outage must not be treated as closed.
            if exc.body['error'] != 'restaurant_closed':
                raise
            late = True
    if not late:
        return None
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        await cur.execute('SELECT payment_status FROM food_order WHERE order_id=%s FOR UPDATE', (evt.order_id,))
        if (await cur.fetchone())['payment_status'] != 'requires_payment':
            return None
        await cur.execute("""INSERT INTO payment_event(provider_event_id,order_id,kind,payment_intent_id,amount_pence,payload)
            VALUES (%s,%s,'cancel_requested',%s,%s,%s) ON CONFLICT(provider_event_id) DO NOTHING RETURNING id""",
            (evt.provider_event_id,evt.order_id,evt.payment_intent_id,evt.amount_pence,Jsonb({'reason':'web_late_payment'})))
        if not await cur.fetchone():
            return 'late_rejected_duplicate'
        await cur.execute("INSERT INTO web_payment_release(order_number,reason) VALUES (%s,'late_payment') ON CONFLICT DO NOTHING", (order['order_number'],))
        await cur.execute("UPDATE thread SET is_active=false WHERE thread_id=%s AND agent='WEB'", (order['thread_id'],))
    return 'late_rejected'

async def sweep():
    if not await flag_enabled('WEB_LATE_PAYMENT_GUARD_ENABLED'):
        return
    await query("""UPDATE thread SET is_active=false WHERE agent='WEB' AND is_active AND thread_id IN
        (SELECT thread_id FROM web_session_meta WHERE expires_at<now())""")
    await query("DELETE FROM web_rate_limit WHERE window_start<now()-interval '2 days'")
    # Claim before I/O; an interrupted attempt becomes eligible again after 1m.
    jobs = await query("""UPDATE web_payment_release SET attempts=attempts+1,next_attempt_at=now()+interval '1 minute',updated_at=now()
        WHERE order_number IN (SELECT order_number FROM web_payment_release WHERE completed_at IS NULL AND next_attempt_at<=now()
        ORDER BY next_attempt_at LIMIT 10 FOR UPDATE SKIP LOCKED) RETURNING order_number,attempts""")
    for job in jobs:
        await release(job['order_number'], job['attempts'])

async def release(order_number, attempts=1):
    from watomation.routers.delivery_hooks import cancel_payment, notify_overwatch
    result = None
    for delay in (0,2,5,15):
        if delay:
            await asyncio.sleep(delay)
        result = await cancel_payment(order_number)
        if result is not None:
            break
    if result is not None:
        await query('UPDATE web_payment_release SET completed_at=now(),updated_at=now() WHERE order_number=%s', (order_number,))
        await customer_notifier.publish(order_number, CustomerOrderEvent('payment_released','payment_released','web-payment-release',{'payment_cancelled':True}))
    else:
        await query("UPDATE web_payment_release SET next_attempt_at=now()+interval '5 minutes' WHERE order_number=%s", (order_number,))
        logger.error('web late-payment release pending order={}', order_number)
        if attempts in (1,3):
            await notify_overwatch(f'{order_number}: late web payment release needs reconciliation; no fulfilment started.')
