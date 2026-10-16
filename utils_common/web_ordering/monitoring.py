"""Daily web price-floor audit, with durable per-day claims and no customer data.

This alerts on client-computed prices; it does not alter the accepted D8 pricing
contract. Missing menu matches are reported as unverifiable, never as valid.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . food_order (table, restaurant-agents): reads (SQL)
  . ordelo_config (table, ordelo_datamodels/core/ordelo_config.sql): reads (SQL)
  . order_item (table, restaurant-agents): reads (SQL)
  . web_monitor_run (table, ordelo_datamodels/ordering/web_monitor_run.sql): reads (SQL), writes (SQL)
(end of database objects)
"""

from decimal import Decimal
from .common import RESTAURANTS, query, one, utcnow
from .availability import UK
from loguru import logger


def below_floor(actual, menu_price, max_discount=0):
    """Test whether a unit price is over one penny below the discounted menu floor.

    Use Decimal arithmetic and reject discount percentages outside 0..100.
    """
    discount = Decimal(str(max_discount))
    if not 0 <= discount <= 100:
        raise ValueError("Invalid configured maximum web discount")
    return Decimal(str(actual)) + Decimal("0.01") < Decimal(str(menu_price)) * (
        1 - discount / 100
    )


async def sweep():
    """Claim and run one price audit per London day across registered restaurants.

    Compare the last 24 hours of web order lines with the lowest menu price
    matching their product name; unmatched lines also require review. Missing
    maximum-discount config means zero. Record unique flagged orders and alert
    ops without changing prices. Delete an unfinished claim on exception so a
    later sweep can retry; a process crash can leave an unfinished claim behind.
    """
    day = utcnow().astimezone(UK).date()
    claimed = await query(
        """INSERT INTO web_monitor_run(run_day) VALUES (%s)
        ON CONFLICT DO NOTHING RETURNING run_day""",
        (day,),
    )
    if not claimed:
        return
    try:
        alerts = []
        for ref in RESTAURANTS:
            config = await one(
                "SELECT config_value FROM ordelo_config WHERE config_key=%s",
                (ref + "_WEB_MAX_DISCOUNT_PERCENT",),
            )
            discount = Decimal(config["config_value"]) if config else Decimal(0)
            if not 0 <= discount <= 100:
                raise ValueError("Invalid web discount limit")
            # Registry is a constant whitelist. ELAS has no SKU column, so use
            # the selected product name for all restaurants, with ambiguity
            # handled conservatively by taking the lowest matching menu price.
            rows = await query(
                """SELECT f.order_number,i.product_name,i.price,min(m.price) AS menu_price
                FROM food_order f JOIN order_item i ON i.order_id=f.order_id
                LEFT JOIN """
                + ref.lower()
                + """_menu m ON lower(trim(m.title))=lower(trim(i.product_name))
                WHERE f.origin_channel='web' AND split_part(f.order_number,'-',1)=%s
                AND f.order_dtts>=now()-interval '1 day'
                GROUP BY f.order_number,i.product_name,i.price""",
                (ref,),
            )
            for row in rows:
                if row["menu_price"] is None or below_floor(
                    row["price"], row["menu_price"], discount
                ):
                    alerts.append(row["order_number"])
        await query(
            "UPDATE web_monitor_run SET completed_at=now(),alert_orders=%s WHERE run_day=%s",
            (list(set(alerts)), day),
        )
        if alerts:
            from watomation.routers.delivery_hooks import notify_overwatch

            await notify_overwatch(
                "Web price audit: check orders " + ", ".join(sorted(set(alerts))[:20])
            )
        logger.info("web price audit day={} flagged_orders={}", day, len(set(alerts)))
    except Exception:
        # Allow the next minute's sweep to recover an unfinished audit.
        await query(
            "DELETE FROM web_monitor_run WHERE run_day=%s AND completed_at IS NULL",
            (day,),
        )
        raise
