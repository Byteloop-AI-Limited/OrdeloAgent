-- Minimal stand-ins for the live tables the Telegram migrations touch, for the ISOLATED test database only.
-- Column lists are cut down to what the migrations and tests use; the real definitions live in
-- ordelo_datamodels/*.sql. Never run this against the shared Supabase database.

CREATE TABLE IF NOT EXISTS public.ordelo_config (
    config_key   text PRIMARY KEY,
    config_value text,
    description  text,
    updated_at   timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.restaurant_master (
    rest_ref  varchar(4) PRIMARY KEY,
    rest_name text NOT NULL,
    admins    text[] NOT NULL DEFAULT '{}'
);

-- The summary tables carry the LIVE constraints as of 15 Oct 2026: delivery_summary.status does NOT yet allow
-- 'declined' (restaurant_order_decision.sql adds it); takeaway_summary already does. Only the columns the
-- migrations and tests use are listed. rest_ref is derived from order_number exactly as in the real tables.
CREATE TABLE IF NOT EXISTS public.delivery_summary (
    order_number   varchar(100) PRIMARY KEY,
    rest_id        varchar(12)  NOT NULL DEFAULT 'R1',
    rest_name      text         NOT NULL DEFAULT 'Test Kitchen',
    customer_id    varchar(50)  NOT NULL DEFAULT '447700900001',
    restaurant_confirmation_status varchar(50) NOT NULL DEFAULT 'restaurant_unconfirmed'
        CHECK (restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline',
               'restaurant_timedout', 'auto_accept', 'auto_decline', 'restaurant_pickuptime_adjusted')),
    restaurant_update_dtts timestamptz,
    restaurant_admin varchar(12),
    status         varchar(50)  NOT NULL DEFAULT 'restaurant_unconfirmed'
        CONSTRAINT delivery_summary_status_check
        CHECK (status IN ('restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed')),
    pickup_time    timestamptz,
    rest_ref       varchar(20) GENERATED ALWAYS AS (split_part(order_number, '-', 1)) STORED,
    dtts           timestamptz  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.takeaway_summary (
    order_number   varchar(100) PRIMARY KEY,
    rest_id        varchar(12)  NOT NULL DEFAULT 'R1',
    rest_name      text         NOT NULL DEFAULT 'Test Kitchen',
    customer_id    varchar(50)  NOT NULL DEFAULT '447700900001',
    restaurant_confirmation_status varchar(50) NOT NULL DEFAULT 'restaurant_unconfirmed'
        CHECK (restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline',
               'restaurant_timedout', 'auto_accept', 'auto_decline')),
    restaurant_update_dtts timestamptz,
    restaurant_admin varchar(12),
    status         varchar(50)  NOT NULL DEFAULT 'restaurant_unconfirmed'
        CHECK (status IN ('restaurant_unconfirmed', 'pickup_confirmed', 'declined', 'completed')),
    pickup_time    timestamptz,
    rest_ref       varchar(20) GENERATED ALWAYS AS (split_part(order_number, '-', 1)) STORED,
    dtts           timestamptz  NOT NULL DEFAULT now()
);

-- Stand-in for the real trigger_restaurant_updates / trigger_takeaway_restaurant_updates (which POST a webhook):
-- records that the trigger would have fired, so tests can prove the decision functions still fire it.
CREATE TABLE IF NOT EXISTS public.trigger_log (id bigserial PRIMARY KEY, tbl text, order_number text, reason text);
CREATE OR REPLACE FUNCTION public.test_log_restaurant_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.trigger_log (tbl, order_number, reason) VALUES (TG_TABLE_NAME, NEW.order_number, NEW.restaurant_confirmation_status);
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS test_restaurant_updates ON public.delivery_summary;
CREATE TRIGGER test_restaurant_updates AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON public.delivery_summary
    FOR EACH ROW EXECUTE FUNCTION public.test_log_restaurant_update();
DROP TRIGGER IF EXISTS test_restaurant_updates ON public.takeaway_summary;
CREATE TRIGGER test_restaurant_updates AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON public.takeaway_summary
    FOR EACH ROW EXECUTE FUNCTION public.test_log_restaurant_update();

-- create_t_invites.sql ends with operator SQL that inserts an invite for ELAS, so the restaurant must exist.
INSERT INTO public.restaurant_master (rest_ref, rest_name) VALUES ('ELAS', 'Elas Kitchen') ON CONFLICT DO NOTHING;

-- ---- create_t_order_alerts.sql needs the order lines, the http extension and parse_alert_offsets -------------------
CREATE TABLE IF NOT EXISTS public.food_order (
    order_id    text PRIMARY KEY,
    order_number text UNIQUE,
    total_price numeric
);
CREATE TABLE IF NOT EXISTS public.order_item (
    id           serial PRIMARY KEY,
    order_id     text,
    product_name text,
    quantity     int
);

-- Stand-in for the pgsql-http extension: http_post() records the call and answers with http_stub_status.
CREATE TYPE public.http_response AS (status int, content_type text, headers text, content text);
CREATE TABLE IF NOT EXISTS public.http_calls (id serial PRIMARY KEY, url text, body text);
CREATE TABLE IF NOT EXISTS public.http_stub_status (status int);
INSERT INTO public.http_stub_status VALUES (200);
CREATE OR REPLACE FUNCTION public.http_post(uri text, content text, content_type text)
RETURNS public.http_response LANGUAGE plpgsql AS $$
DECLARE s int;
BEGIN
    INSERT INTO public.http_calls (url, body) VALUES (uri, content);
    SELECT status INTO s FROM public.http_stub_status LIMIT 1;
    RETURN ROW(s, 'application/json', NULL, '{}')::public.http_response;
END $$;

-- Verbatim from ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql (section 3).
CREATE OR REPLACE FUNCTION parse_alert_offsets(p_config_key text)
RETURNS int[] LANGUAGE sql STABLE AS $$
    SELECT array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
      FROM ordelo_config c
     CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t(x)
     WHERE c.config_key = p_config_key
       AND btrim(t.x) ~ '^-?\d+$';
$$;
