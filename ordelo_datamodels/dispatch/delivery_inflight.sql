-- See also (paths under ordelo_datamodels/): the Ready / +10 / +20 rule that gates on this table's pickup and cancellation state, with its row locks, is in restaurant_admin/restaurant_ready_adjust_notices.sql.
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
  PERFORM set_config('statement_timeout', '10000', true);
  -- Combine the NEW record with additional data from delivery_detail, delivery_summary, and rider_master; required to invoke graph
  SELECT json_build_object(
    'delivery_inflight', json_build_array(row_to_json(NEW)),
    'delivery_summary', (
      SELECT row_to_json(summ)
      FROM delivery_summary summ
      WHERE summ.order_number = NEW.order_number
      LIMIT 1
    ),
    'rider_master', (
      SELECT row_to_json(rm)
      FROM (
        SELECT rider_name, rider_id
        FROM rider_master
        WHERE rider_id = NEW.rider_id
        LIMIT 1
      ) rm
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
DROP TRIGGER IF EXISTS trigger_delivery_inflight_whook ON public.delivery_inflight;
CREATE TRIGGER trigger_delivery_inflight_whook AFTER INSERT ON delivery_inflight FOR EACH ROW EXECUTE FUNCTION delivery_inflight_whook();

----------------------------------------
-- notify_missed_dispatches - Identifies dispatches that have timed out and notifies the system
----------------------------------------
-- (The statement that followed this comment is now generated from live in dispatch/notify_missed_dispatches.sql.)

-- Table definition
CREATE TABLE IF NOT EXISTS public.delivery_inflight (
    dispatch_id integer NOT NULL,
    order_number character varying(100) NOT NULL,
    rider_id character varying(12) NOT NULL,
    customer_id character varying(12) NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT delivery_inflight_pkey PRIMARY KEY (dispatch_id)
);
