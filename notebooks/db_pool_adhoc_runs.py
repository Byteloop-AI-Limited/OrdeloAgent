# %%
from config import client_ordelo

riders = ["447448440754", "447448440755"]
(
    client_ordelo.table("rider_master")
    .update({"is_in_shift": False, "shift_response_dtts": None})
    .in_("rider_id", riders)
    .execute()
)

# %% To be changed later
# %%

from timeit import timeit
import psycopg
from psycopg_pool import ConnectionPool
import os
from config import pg_settings
import asyncio
from datetime import datetime
from config import _sync_wa_client

# Database connection parameters
DB_URL = pg_settings.db_uri


def process_dispatch_response_from_rider(
    recipient: str, callback_data: dict, _sync_wa_client: _sync_wa_client
):
    """
    Process rider's response to a delivery dispatch in a sync context.

    This function executes database operations in an async context.

    Args:
        recipient: The phone number of the recipient.
        callback_data: The callback data containing the dispatch ID and order number.
        _sync_wa_client: An instance of the AsyncWhatsApp client.

    Returns:
        None
    """
    # Create a new pool for this function call
    pool = ConnectionPool(DB_URL)

    try:
        pool.open()

        _dispatch_id = callback_data["dispatch_id"]
        _order_number = callback_data["order_number"]
        rider_response = callback_data["status"]

        with pool.connection() as conn:
            with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                if rider_response == "declined":
                    cur.execute(
                        """
                        UPDATE delivery_dispatch 
                        SET status = 'declined', status_update_dtts = %s 
                        WHERE dispatch_id = %s
                        """,
                        (datetime.now().isoformat(), _dispatch_id),
                    )

                elif rider_response == "accepted":
                    # Check current status
                    cur.execute(
                        "SELECT status FROM delivery_detail WHERE order_number = %s",
                        (_order_number,),
                    )
                    _detail = cur.fetchone()

                    if _detail and _detail["status"] == "assigned":
                        # Job already assigned
                        _sync_wa_client.send_message(
                            to=recipient,
                            text="Sorry, This job has already been assigned",
                        )
                    else:
                        # Update dispatch status
                        cur.execute(
                            """
                            UPDATE delivery_dispatch 
                            SET status = 'assigned', status_update_dtts = %s 
                            WHERE dispatch_id = %s
                            """,
                            (datetime.now().isoformat(), _dispatch_id),
                        )

                        # Update delivery detail
                        cur.execute(
                            """
                            UPDATE delivery_detail 
                            SET status = 'assigned', dispatch_id = %s, rider_id = %s 
                            WHERE order_number = %s
                            """,
                            (_dispatch_id, recipient, _order_number),
                        )

                conn.commit()

    except Exception as e:
        print(f"Error processing dispatch response: {e}")
        raise
    finally:
        if pool and not pool.closed:
            pool.close()


# %% Test
process_dispatch_response_from_rider(
    recipient="447448440754",
    callback_data={"dispatch_id": 123, "order_number": "test123", "status": "accepted"},
    _sync_wa_client=_sync_wa_client,
)
