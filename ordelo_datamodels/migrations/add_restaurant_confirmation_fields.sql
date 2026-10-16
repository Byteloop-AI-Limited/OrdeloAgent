-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Columns and constraint applied; its trigger trigger_restaurant_confirmation_request and function
--               restaurant_confirmation_whook() were later replaced (trigger_restaurant_updates / restaurant_updates_whook()).
-- Current definitions now live in: _orphans/delivery.sql
--               delivery/delivery_summary.sql
-- Purpose: Restaurant confirmation columns, status 'restaurant_unconfirmed' and the first confirmation trigger (Nov 2025).
-- The feature files above are the current truth; this file only records the one-off change.

/**
Migration: Add Restaurant Confirmation Fields to delivery_summary
Date: 2025-11-18
Purpose: Support restaurant confirmation touchpoint before rider dispatch

Changes:
1. Add new columns for restaurant confirmation tracking
2. Update status CHECK constraint to include 'restaurant_unconfirmed'
3. Add trigger function for restaurant confirmation webhook
4. Add trigger to fire on new restaurant_unconfirmed orders
**/

-- Step 1: Add new columns to delivery_summary
ALTER TABLE delivery_summary
  ADD COLUMN rest_confirmed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN rest_prep_time_minutes INTEGER,
  ADD COLUMN rest_confirmation_method VARCHAR(20) 
    CHECK (rest_confirmation_method IN ('manual', 'timeout', NULL));

-- Step 2: Update status CHECK constraint to include new status
ALTER TABLE delivery_summary 
  DROP CONSTRAINT delivery_summary_status_check,
  ADD CONSTRAINT delivery_summary_status_check 
    CHECK (status IN (
      'restaurant_unconfirmed',
      'unassigned', 
      'timedout', 
      'assigned', 
      'completed'
    ));

-- Step 3: Create webhook function for restaurant confirmation request
CREATE OR REPLACE FUNCTION restaurant_confirmation_whook()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
  response json;
BEGIN
  -- Only trigger for new restaurant_unconfirmed orders
  IF NEW.status = 'restaurant_unconfirmed' THEN
    
    -- Build payload
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'created_at', NEW.dtts
    ) INTO webhook_payload;
    
    -- Get webhook URL from config
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
    
    -- Make HTTP POST
    response := (
      SELECT content
      FROM http_post(
        webhook_url,
        webhook_payload::text,
        'application/json'
      )
    );
    
    RAISE NOTICE 'Restaurant confirmation request sent for order %: %', NEW.order_number, response;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Step 4: Create trigger
CREATE TRIGGER trigger_restaurant_confirmation_request
AFTER INSERT ON delivery_summary
FOR EACH ROW
WHEN (NEW.status = 'restaurant_unconfirmed')
EXECUTE FUNCTION restaurant_confirmation_whook();

-- Step 5: Add configuration values
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES 
  ('RESTAURANT_CONFIRMATION_TIMEOUT', '5', 'Default minutes to wait for restaurant confirmation before defaulting to max prep time')
ON CONFLICT (config_key) DO NOTHING;

-- Note: Restaurant-specific timeouts can be added as:
-- INSERT INTO ordelo_config (config_key, config_value, description)
-- VALUES ('{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT', '3', 'Custom timeout for specific restaurant');
