-- Takeaway summary table and restaurant-confirmation webhook trigger.

CREATE TABLE takeaway_summary (
    order_number          VARCHAR(100) PRIMARY KEY,
    rest_id               VARCHAR(12) NOT NULL,
    rest_name             TEXT NOT NULL,
    rest_address          TEXT NOT NULL,
    town                  VARCHAR(255) NOT NULL,
    customer_id           VARCHAR(50) NOT NULL,
    customer_name         TEXT NOT NULL,
    restaurant_confirmation_status VARCHAR(50) NOT NULL DEFAULT 'restaurant_unconfirmed'
        CHECK (
            restaurant_confirmation_status IN (
                'restaurant_unconfirmed',
                'restaurant_accept',
                'restaurant_decline',
                'restaurant_timedout',
                'auto_accept',
                'auto_decline'
            )
        ),
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE,
    restaurant_admin       VARCHAR(12),
    status                 VARCHAR(50) NOT NULL
        CHECK (
            status IN (
                'restaurant_unconfirmed',
                'pickup_confirmed',
                'declined',
                'completed'
            )
        ),
    rest_confirmation_code INTEGER NOT NULL,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR(20),
    restaurant_msg_id      VARCHAR(255),
    customer_msg_id        VARCHAR(255),
    pickup_time            TIMESTAMP WITH TIME ZONE,
    pickup_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    rest_ref               VARCHAR(20) GENERATED ALWAYS AS (SPLIT_PART(order_number, '-', 1)) STORED,
    dt                     DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts                   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

/** description: takeaway_restaurant_updates_whook
 *  purpose: Sends a webhook request to the Ordelo app for takeaway restaurant confirmation workflow events
 *  parameters:
 *    - NEW: The new/updated takeaway_summary record
 *    - OLD: The old takeaway_summary record (for UPDATE operations)
 *  returns:
 *    - TRIGGER: The trigger object
 */
CREATE OR REPLACE FUNCTION takeaway_restaurant_updates_whook()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
  response json;
  takeaway_summary_json json;
  restaurant_master_json json;
  food_order_json json;
  order_items_json json;
  food_order_id text;
  trigger_reason text;
  p_log_to_table BOOLEAN := TRUE;
BEGIN
  PERFORM set_config('statement_timeout', '10000', true);

  BEGIN
    SELECT COALESCE((config_value::BOOLEAN), TRUE)
      INTO p_log_to_table
    FROM ordelo_config
    WHERE config_key = 'ENABLE_TRIGGER_DEBUG_LOG';
  EXCEPTION
    WHEN OTHERS THEN
      p_log_to_table := TRUE;
  END;

  trigger_reason := NEW.restaurant_confirmation_status;

  IF p_log_to_table THEN
    INSERT INTO debug_log (trigger_name, order_number, message)
    VALUES (
      'takeaway_confirmation_whook',
      NEW.order_number,
      'Trigger fired, trigger_reason: ' || trigger_reason || ', TG_OP: ' || TG_OP
    );
  END IF;

  IF NEW.restaurant_confirmation_status IN (
    'restaurant_unconfirmed',
    'restaurant_accept',
    'restaurant_decline',
    'restaurant_timedout'
  ) THEN
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'rest_address', NEW.rest_address,
      'town', NEW.town,
      'customer_id', NEW.customer_id,
      'customer_name', NEW.customer_name,
      'restaurant_confirmation_status', NEW.restaurant_confirmation_status,
      'restaurant_update_dtts', NEW.restaurant_update_dtts,
      'restaurant_admin', NEW.restaurant_admin,
      'status', NEW.status,
      'rest_confirmation_code', NEW.rest_confirmation_code,
      'rest_prep_time_minutes', NEW.rest_prep_time_minutes,
      'rest_confirmation_method', NEW.rest_confirmation_method,
      'restaurant_msg_id', NEW.restaurant_msg_id,
      'customer_msg_id', NEW.customer_msg_id,
      'pickup_time', NEW.pickup_time,
      'pickup_date', NEW.pickup_date,
      'rest_ref', NEW.rest_ref,
      'dt', NEW.dt,
      'dtts', NEW.dtts
    )
    INTO takeaway_summary_json;

    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES (
        'takeaway_confirmation_whook',
        NEW.order_number,
        'Takeaway summary JSON built'
      );
    END IF;

    SELECT json_build_object(
      'rest_id', rm.rest_id,
      'rest_ref', rm.rest_ref,
      'rest_name', rm.rest_name,
      'admins', rm.admins,
      'lon', rm.lon,
      'lat', rm.lat,
      'house_number', rm.house_number,
      'building_name', rm.building_name,
      'street_name', rm.street_name,
      'city', rm.city,
      'postcode', rm.postcode
    )
    INTO restaurant_master_json
    FROM restaurant_master rm
    WHERE rm.rest_id = NEW.rest_id;

    SELECT
      json_build_object(
        'order_id', fo.order_id,
        'order_number', fo.order_number,
        'seq_id', fo.seq_id,
        'recipient', fo.recipient,
        'thread_id', fo.thread_id,
        'action', fo.action,
        'total_price', fo.total_price,
        'final_order_value', fo.final_order_value,
        'rest_cost', fo.rest_cost,
        'service_charge', fo.service_charge,
        'delivery_fee', fo.delivery_fee,
        'small_order_fee', fo.small_order_fee,
        'commission_rate', fo.commission_rate,
        'payment_status', fo.payment_status
      ),
      fo.order_id
    INTO food_order_json, food_order_id
    FROM food_order fo
    WHERE fo.order_number = NEW.order_number;

    IF food_order_json IS NULL THEN
      IF p_log_to_table THEN
        INSERT INTO debug_log (trigger_name, order_number, message)
        VALUES (
          'takeaway_confirmation_whook',
          NEW.order_number,
          'WARNING: No food_order found for order_number'
        );
      END IF;
      RAISE WARNING 'No food_order found for order_number %', NEW.order_number;
      RETURN NEW;
    END IF;

    SELECT json_agg(
      json_build_object(
        'order_id', oi.order_id,
        'sku', oi.sku,
        'quantity', oi.quantity,
        'price', oi.price,
        'product_name', oi.product_name
      )
    )
    INTO order_items_json
    FROM order_item oi
    WHERE oi.order_id = food_order_id;

    SELECT json_build_object(
      'trigger_reason', trigger_reason,
      'takeaway_summary', takeaway_summary_json,
      'restaurant_master', restaurant_master_json,
      'food_order', food_order_json,
      'order_items', COALESCE(order_items_json, '[]'::json)
    )
    INTO webhook_payload;

    SELECT config_value
      INTO ordelo_app_url
    FROM ordelo_config
    WHERE config_key = 'ORDELO_APP_URL';

    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;

    webhook_url := ordelo_app_url || '/takeaway-hooks/restaurant-confirmation-request';

    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message, payload)
      VALUES (
        'takeaway_confirmation_whook',
        NEW.order_number,
        'Posting webhook to ' || webhook_url,
        webhook_payload::jsonb
      );
    END IF;

    response := (
      SELECT content
      FROM http_post(
        webhook_url,
        webhook_payload::text,
        'application/json'
      )
    );

    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message, payload)
      VALUES (
        'takeaway_confirmation_whook',
        NEW.order_number,
        'HTTP response received',
        response::jsonb
      );
    END IF;
  END IF;

  RETURN NEW;
EXCEPTION
  WHEN OTHERS THEN
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES (
        'takeaway_confirmation_whook',
        NEW.order_number,
        'ERROR: ' || SQLERRM
      );
    END IF;
    RAISE WARNING 'Error in takeaway_restaurant_updates_whook for order %: %', NEW.order_number, SQLERRM;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_takeaway_restaurant_updates
AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON public.takeaway_summary
FOR EACH ROW
WHEN (
  NEW.restaurant_confirmation_status IN (
    'restaurant_unconfirmed',
    'restaurant_accept',
    'restaurant_decline',
    'restaurant_timedout'
  )
)
EXECUTE FUNCTION takeaway_restaurant_updates_whook();
