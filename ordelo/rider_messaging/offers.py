"""
The job offer a rider sees, built from one offer row (the bulk_dispatch item of delivery_dispatch_whook_statement() in
ordelo_datamodels/dispatch/delivery_dispatch.sql, or the 'offer' object of rider_offer_reminder_snapshot() in
ordelo_datamodels/dispatch/rider_offer_alert.sql; same keys, same JSON types).
    . job_offer(row, dispatch_id=None) -> JobOffer: header "<distance> miles, £<payout>, @<pickup>" and the WhatsApp-style
      body, byte-identical to what delivery_hooks.wa_send_delivery_dispatch_request_to_rider sent before (golden test).
  Classes/Functions:
    . job_offer
"""

from __future__ import annotations

from typing import Any, Mapping

from utils_common.tz_utils import fmt_uk_time

from .models import JobOffer


def job_offer(row: Mapping[str, Any], dispatch_id: int | None = None) -> JobOffer:
    pickup_time = fmt_uk_time(row["pickup_time"])
    header_text = f"{row['distance']} miles, £{row['rider_payout']}, @{pickup_time}"
    wa_text = f"""
    Pickup time - *{pickup_time}*

Pickup location - *{row["rest_name"]}*
{row["rest_address"]}

Drop off location - *{row["customer_name"]}*
{row["customer_address"]}

Order number - *{row["order_number"]}*

Vehicle type - *{row["vehicle_type"]}*
    """
    return JobOffer(
        dispatch_id=dispatch_id if dispatch_id is not None else int(row["dispatch_id"]),
        order_number=row["order_number"],
        header=header_text,
        text=wa_text,
    )
