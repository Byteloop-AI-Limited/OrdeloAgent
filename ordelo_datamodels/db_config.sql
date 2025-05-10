CREATE TABLE IF NOT EXISTS app_config (
    config_key TEXT PRIMARY KEY,
    config_value TEXT NOT NULL
);

INSERT INTO app_config (config_key, config_value)
VALUES ('dispatch_batch_limit', '1')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;


-- example usage
CREATE OR REPLACE FUNCTION job_create_dispatch()
RETURNS void AS $$
DECLARE
  has_unassigned BOOLEAN;
  batch_limit INT;
BEGIN
  -- Get the batch limit from config
  SELECT config_value::INT INTO batch_limit
  FROM app_config
  WHERE config_key = 'dispatch_batch_limit';

  -- Check if there are any unassigned orders
  SELECT EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' LIMIT 1) INTO has_unassigned;
  
  IF has_unassigned THEN
    WITH availableRiders AS (
        -- ... your existing CTE ...
    ), dispatch_insert AS (
        INSERT INTO delivery_dispatch(...)
        SELECT ...
        FROM availableRiders
        WHERE rider_count > 0
        LIMIT batch_limit -- Use the runtime config here!
        RETURNING order_number
    )
    -- ... rest of your function ...
  END IF;
END;
$$ LANGUAGE plpgsql;