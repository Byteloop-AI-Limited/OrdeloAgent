-- 1. Create custom enum types
-- DROP TYPE vehicle_type_enum cascade;

-- 2. Driver Master Table
-- (The statement that followed this comment is now generated from live in core/rider_master.sql.)
CREATE TABLE IF NOT EXISTS public.restaurant_master (
    rest_ref character varying(4) NOT NULL,
    rest_id character varying(12),
    rest_name text NOT NULL,
    rest_email text,
    house_number text NOT NULL,
    building_name text,
    street_name text NOT NULL,
    city text NOT NULL,
    postcode text NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    admins text[],
    rest_stale_active_threads_minutes integer NOT NULL DEFAULT 10,
    restaurant_start_time double precision NOT NULL DEFAULT 12,
    restaurant_end_time double precision NOT NULL DEFAULT 21.30,
    service_hours_json jsonb NOT NULL DEFAULT '{}' ::jsonb,
    collection_commission double precision,
    auto_accept boolean NOT NULL DEFAULT FALSE,
    delivery_order_cutoff_minutes integer NOT NULL DEFAULT 0, -- added by migrations/add_order_cutoff_minutes.sql
    takeaway_order_cutoff_minutes integer NOT NULL DEFAULT 0, -- added by migrations/add_order_cutoff_minutes.sql
    CONSTRAINT restaurant_master_pkey PRIMARY KEY (rest_ref),
    CONSTRAINT restaurant_master_rest_id_key UNIQUE (rest_id)
);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- LTER TABLE customer_master
--   DROP COLUMN IF EXISTS consented_rest_refs;

-- SELECT
--     column_name,
--     data_type,
--     is_nullable,
--     column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND table_name = 'customer_master'
-- ORDER BY ordinal_position;
