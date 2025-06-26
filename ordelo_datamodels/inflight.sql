/**
Delivery Inflight Trigger – Step 5 in Delivery Workflow

Where This Fits in the Journey:
    - This function is the fifth step in the delivery agent workflow, as outlined in handwritten_design.md.
    - Step 1: init_delivery – Creates delivery_summary and calls process_delivery().
    - Step 2: process_delivery – Creates delivery_detail records and manages assignment/timeouts.
    - Step 3: job_create_dispatch – Creates dispatches for available riders, updates statuses.
    - Step 4: job_assign_dispatch – Assigns dispatches to riders who have accepted, updates statuses, and inserts into delivery_inflight.
    - Step 5: delivery_inflight_whook (this function) – Triggered by insert into delivery_inflight, kicks off rider graph and missed dispatch notifications.
    - Step 6+: Downstream jobs and triggers handle any further notification or tracking.

Invocation:
    - Row-level trigger AFTER INSERT on `delivery_inflight`.
    - Fires per new `delivery_inflight` row.

Purpose:
    - Kick off the rider graph flow via HTTP POST to `/delivery-hooks/delivery-inflight-graph-init`.
    - Notify missed dispatches by calling `notify_missed_dispatches()`.

Dependencies:
    - Reads from: `delivery_inflight`, `delivery_detail`.
    - Calls: HTTP POST to webhook, `notify_missed_dispatches()`.

Side Effects:
    1. HTTP POST to graph-init endpoint.
    2. Calls `notify_missed_dispatches`.
    3. Enables downstream notification and tracking jobs.

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/ -- Webhook function for delivery_inflight

CREATE OR REPLACE FUNCTION public.delivery_inflight_whook() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  response json;
  webhook_payload json;
  notify_result BOOLEAN;
  app_url VARCHAR;
  hook_url VARCHAR;
BEGIN
  -- Combine the NEW record with additional data from delivery_detail; required to invoke graph
  SELECT json_build_object(
    'delivery_inflight', json_build_array(row_to_json(NEW)),
    'delivery_detail', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT
          det.order_number,
          det.vehicle_type,
          det.rider_payout,
          det.distance,
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
          summ.customer_address,
          det.status,
          det.dispatch_id,
          det.rider_id
        FROM delivery_detail det
        INNER JOIN delivery_summary summ
          ON det.order_number = summ.order_number
        WHERE det.order_number = NEW.order_number
          AND det.dispatch_id = NEW.dispatch_id
        LIMIT 1
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://agent.ordelo.app';
  END IF;

  -- Ensure no trailing slash before appending path
  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/delivery-hooks/delivery-inflight-graph-init';

  response := (
    SELECT content
    FROM http_post(
      hook_url,
      webhook_payload::text,
      'application/json'
    )
  );

  -- Log the response
  RAISE NOTICE 'Response from HTTP POST to delivery-inflight-graph-init: %', response;

  -- Call notify_missed_dispatches_for_order with the order number
  SELECT  notify_missed_dispatches() INTO notify_result;

  -- Log the result of notify_missed_dispatches_for_order
  RAISE NOTICE 'Result of notify_missed_dispatches for order %: %', NEW.order_number, notify_result;

  RETURN NEW;
END;
$$;

-- Trigger to call the webhook

CREATE TRIGGER trigger_delivery_inflight_whook AFTER
INSERT ON public.delivery_inflight
FOR EACH ROW EXECUTE FUNCTION public.delivery_inflight_whook();

----------------------------------------
-- notify_missed_dispatches - Identifies dispatches that have timed out and notifies the system
----------------------------------------

DROP FUNCTION IF EXISTS notify_missed_dispatches();


CREATE OR REPLACE FUNCTION notify_missed_dispatches() RETURNS BOOLEAN AS $$
DECLARE
    response json;
    webhook_payload json;
    notified BOOLEAN := FALSE;
    app_url VARCHAR;
    hook_url VARCHAR;
BEGIN
    WITH missed_dispatches AS (
        SELECT
            dd.order_number,
            json_agg(json_build_object(
                'dispatch_id', d.dispatch_id,
                'rider_id', d.rider_id,
                'order_number', d.order_number,
                'order_status', dd.status,
                'dtts', d.dtts
            )) AS dispatches
        FROM delivery_dispatch d
        INNER JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.status = 'accepted'
        -- AND DATE(d.dtts) = DATE(dd.dtts)
        AND dd.status = 'assigned'
        GROUP BY dd.order_number
    )
    SELECT
        json_build_object(
            'missed_dispatches', (
                SELECT json_agg(row_to_json(md))
                FROM missed_dispatches md
            )
        ) INTO webhook_payload;

    -- Make the HTTP POST request with the payload
    SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://agent.ordelo.app';
  END IF;

  -- Ensure no trailing slash before appending path
  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/delivery-hooks/notify-missed-dispatches';
    response := (
        SELECT content
        FROM http_post(
            hook_url,
            webhook_payload::text,
            'application/json'
        )
    );

    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;

    RETURN notified;
END;
$$ LANGUAGE plpgsql;

-- Table definition
CREATE TABLE delivery_inflight (
    dispatch_id    INTEGER PRIMARY KEY,
    order_number   VARCHAR(100) NOT NULL,
    rider_id       VARCHAR(12) NOT NULL,
    customer_id    VARCHAR(12) NOT NULL,
    dt             DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);