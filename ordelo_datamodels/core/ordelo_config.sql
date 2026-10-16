-- Table to store application configuration as key-value pairs
CREATE TABLE ordelo_config (
    config_key     VARCHAR(100) PRIMARY KEY,
    config_value   TEXT NOT NULL,
    description    TEXT,
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- -- Optional: trigger to auto-update "updated_at" on row modification
-- CREATE OR REPLACE FUNCTION trigger_update_timestamp()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     NEW.updated_at = CURRENT_TIMESTAMP;
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;

-- CREATE TRIGGER trg_app_config_updated
-- BEFORE UPDATE ON app_config
-- FOR EACH ROW
-- EXECUTE FUNCTION trigger_update_timestamp();

-- update restaurant_master 
-- set admins = '{}'::text[]
-- where rest_ref='WREN';