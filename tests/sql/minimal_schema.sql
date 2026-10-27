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

-- The summary tables mirror the live shape defined in ordelo_datamodels/delivery/delivery_summary.sql and
-- takeaway/takeaway_summary.sql (live check 16 Oct 2026): status allows 'declined', and the kitchen columns used by
-- restaurant_admin/restaurant_ready_adjust_notices.sql are present. Only the columns the feature files and tests use
-- are listed. rest_ref is derived from order_number exactly as in the real tables.
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
        CHECK (status IN ('restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed', 'declined')),
    pickup_time    timestamptz,
    pickup_date    date         NOT NULL DEFAULT CURRENT_DATE,
    rest_confirmation_code integer NOT NULL DEFAULT 42,
    cust_confirmation_code integer NOT NULL DEFAULT 57,
    rest_address text NOT NULL DEFAULT 'Test Kitchen',
    customer_name text NOT NULL DEFAULT 'Test Customer',
    customer_address text NOT NULL DEFAULT '1 High Street, Testville',
    ready_at       timestamptz,
    ready_by       text,
    ready_dispatch_id integer,
    pickup_time_initial timestamptz,
    pickup_adjusted_by text,
    pickup_adjusted_at timestamptz,
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
    pickup_date    date         NOT NULL DEFAULT CURRENT_DATE,
    rest_confirmation_code integer NOT NULL DEFAULT 42,
    ready_at       timestamptz,
    ready_by       text,
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

-- t_invites.sql ends with operator SQL that inserts an invite for ELAS, so the restaurant must exist.
INSERT INTO public.restaurant_master (rest_ref, rest_name) VALUES ('ELAS', 'Elas Kitchen') ON CONFLICT DO NOTHING;

-- ---- t_order_alerts.sql needs the order lines, the http extension and parse_alert_offsets -------------------
CREATE TABLE IF NOT EXISTS public.food_order (
    order_id    text PRIMARY KEY,
    order_number text UNIQUE,
    total_price numeric,
    notes       text,
    small_order_fee float,
    payment_status text NOT NULL DEFAULT 'paid',
    recipient   text NOT NULL DEFAULT '447700900001',
    order_dtts timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.order_item (
    id           serial PRIMARY KEY,
    order_id     text,
    product_name text,
    quantity     int,
    price        float NOT NULL DEFAULT 0,
    modifications text[]
);

-- ---- restaurant_ready_adjust_notices.sql needs the dispatch tables and riders (columns used only) ----------------------
-- rider_master: the R1 target shape (ordelo_datamodels/core/rider_master.sql). town / vehicle_type / status get test-only
-- defaults so older tests can insert (rider_id, rider_name) alone; the live table has no such defaults.
CREATE TABLE IF NOT EXISTS public.rider_master (
    id           serial PRIMARY KEY,
    rider_id     varchar(12) NOT NULL,
    rider_name   text NOT NULL,
    vehicle_type varchar(15) NOT NULL DEFAULT 'bike',
    town         varchar(255) NOT NULL DEFAULT 'dummy',
    status       varchar(50) NOT NULL DEFAULT 'active',
    is_in_shift  boolean NOT NULL DEFAULT true,
    priority     int NOT NULL DEFAULT 1,
    dtts         timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_response_dtts timestamp,
    channel      text NOT NULL DEFAULT 'whatsapp' CHECK (channel IN ('whatsapp', 'telegram')),
    tuid         bigint,
    tcid         bigint,
    t_username   text,
    t_first_name text,
    t_linked_at  timestamptz,
    phone_verified boolean NOT NULL DEFAULT false,
    CONSTRAINT rider_master_rider_id_key UNIQUE (rider_id),
    CONSTRAINT rider_master_tg_link_complete CHECK ((tuid IS NULL) = (tcid IS NULL))
);
CREATE TABLE IF NOT EXISTS public.delivery_dispatch (
    dispatch_id serial PRIMARY KEY,
    order_number varchar(100) NOT NULL,
    rider_id    varchar(12) NOT NULL,
    status      varchar(50) NOT NULL CHECK (status IN ('unassigned', 'timedout', 'declined', 'accepted', 'missed', 'assigned', 'pickedup', 'completed')),
    status_update_dtts timestamp,
    reason_for_decline text,
    vehicle_type varchar(15) NOT NULL DEFAULT 'bike',
    rider_payout double precision NOT NULL DEFAULT 3.25,
    distance double precision NOT NULL DEFAULT 1.5,
    dtts timestamp NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
    paid_status text NOT NULL DEFAULT 'unpaid',
    paid_dtts timestamp,
    -- R2-R4 target shape (ordelo_datamodels/dispatch/delivery_dispatch.sql)
    channel     text NOT NULL DEFAULT 'whatsapp' CHECK (channel IN ('whatsapp', 'telegram')),
    channel_msg_ref text,
    thread_id   text
);
-- thread: owned by restaurant-agents (shape from utils_common/thread_management/thread_mgmnt_ddl.sql).
CREATE TABLE IF NOT EXISTS public.thread (
    thread_id text PRIMARY KEY,
    agent text,
    recipient varchar(12),
    is_active boolean,
    retain_thread boolean DEFAULT false,
    dt date DEFAULT current_date,
    dtts timestamp DEFAULT current_timestamp,
    last_access_dtts timestamp DEFAULT current_timestamp
);
CREATE TABLE IF NOT EXISTS public.delivery_inflight (
    dispatch_id  integer PRIMARY KEY,
    order_number varchar(100) NOT NULL,
    rider_id     varchar(12) NOT NULL
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

-- Verbatim from ordelo_datamodels/dispatch/job_rider_pickup_alerts.sql (section 3).
CREATE OR REPLACE FUNCTION parse_alert_offsets(p_config_key text)
RETURNS int[] LANGUAGE sql STABLE AS $$
    SELECT array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
      FROM ordelo_config c
     CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t(x)
     WHERE c.config_key = p_config_key
       AND btrim(t.x) ~ '^-?\d+$';
$$;
