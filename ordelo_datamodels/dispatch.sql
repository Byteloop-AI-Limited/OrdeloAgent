/**
Batch Dispatch Webhook Trigger

Invocation:
1. Statement-level trigger on `delivery_dispatch` INSERTs

Purpose:
- Aggregate newly inserted dispatch rows into a bulk JSON payload
- Enrich with details from `delivery_detail` and `delivery_summary`

Depends on tables: `delivery_dispatch`, `delivery_detail`, `delivery_summary`

Execution:
- Fires once per INSERT statement (statement-level trigger)

Side Effects:
1. Sends single HTTP POST to `/delivery-hooks/delivery-dispatch` with bulk payload
**/ -- Drop existing bulk trigger if any
-- DROP TRIGGER IF EXISTS trigger_delivery_dispatch_whook ON public.delivery_dispatch;
 -- Trigger function to process batch inserts

CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook_statement() RETURNS trigger AS $$
DECLARE
  response json;
  webhook_payload json;
  app_url varchar;
  hook_url varchar;
BEGIN
  PERFORM set_config('statement_timeout', '10000', true);
  -- Build payload by joining new_rows with delivery_detail in one query
  SELECT json_build_object(
    'bulk_dispatch', json_agg(row_to_json(t))
  )
  INTO webhook_payload
  FROM (
    SELECT
      nr.dispatch_id,
      nr.order_number,
      nr.rider_id,
      nr.rider_payout,
      nr.vehicle_type,
      nr.distance,
      summ.pickup_time,
      summ.rest_id,
      summ.rest_name,
      summ.rest_lon,
      summ.rest_lat,
      summ.rest_address,
      summ.town,
      summ.customer_id,
      summ.customer_name,
      summ.customer_lon,
      summ.customer_lat,
      summ.customer_address
    FROM new_rows nr
    JOIN delivery_detail det ON nr.order_number = det.order_number AND det.vehicle_type = nr.vehicle_type
    JOIN delivery_summary summ ON summ.order_number = nr.order_number
  ) t;

  -- Send single HTTP POST for all new rows
  SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://rider-agent.ordelo.app';
  END IF;

  -- Ensure no trailing slash before appending path
  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/delivery-hooks/delivery-dispatch';

  response := (
    SELECT content
    FROM http_post(
      hook_url,
      webhook_payload::text,
      'application/json'
    )
  );
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

drop table delivery_dispatch; -- Dont forget to recreate the trigger
-- Table definition
CREATE TABLE delivery_dispatch (
    dispatch_id SERIAL PRIMARY KEY,
    order_number VARCHAR(100) NOT NULL,
    rider_id VARCHAR(12) NOT NULL,
    rider_payout DOUBLE PRECISION NOT NULL,
    vehicle_type VARCHAR(15) NOT NULL,
    distance DOUBLE PRECISION NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (
        status IN (
            'unassigned',
            'timedout',
            'declined',
            'accepted',
            'missed',
            'assigned',
            'pickedup',
            'completed'
        )
    ),
	    status_update_dtts TIMESTAMP,
	    reason_for_decline TEXT,
	    dt DATE NOT NULL DEFAULT CURRENT_DATE,
	    dtts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
	);

-- Statement-level trigger on batch insert

CREATE TRIGGER trigger_delivery_dispatch_whook AFTER
INSERT ON public.delivery_dispatch REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION public.delivery_dispatch_whook_statement();

-- ---------------------------------------------------------------------------
-- Payout tracking columns (rider dashboard)
-- ---------------------------------------------------------------------------
ALTER TABLE delivery_dispatch
  ADD COLUMN IF NOT EXISTS paid_status VARCHAR(20) NOT NULL DEFAULT 'unpaid'
    CHECK (paid_status IN ('unpaid', 'paid')),
  ADD COLUMN IF NOT EXISTS paid_dtts  TIMESTAMP;

-- Enforce: paid_dtts must be set iff paid_status='paid';
-- ALTER TABLE delivery_dispatch
--   ADD CONSTRAINT IF NOT EXISTS delivery_dispatch_paid_dtts_consistency
--     CHECK (
--       (paid_status = 'paid'   AND paid_dtts IS NOT NULL) OR
--       (paid_status = 'unpaid' AND paid_dtts IS NULL)
--     );

-- Partial index for fast paid/unpaid queries on the rider dashboard
CREATE INDEX IF NOT EXISTS delivery_dispatch_paid_status_dt_idx
  ON delivery_dispatch (paid_status, dt DESC);
