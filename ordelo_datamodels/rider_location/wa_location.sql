-- =============================================================================================
-- ordelo_datamodels/rider_location/wa_location.sql
-- On-demand WhatsApp rider location: who asked where the rider is (requests) and the locations received (observations).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
--               EXCEPT phase R5 of plans/telegram-rider-bot-plan.md (not yet live; migrations/rider_telegram_r5_r6.sql step 1):
--                 wa_location_observation_source_check also allows 'telegram_current' (D50).
-- OBJECTS       table  wa_location_observation
--                   One rider location received on demand (rider GPS share, or the restaurant location inferred at confirmation).
--               table  wa_location_request
--                   One requester waiting for (or already sent) the rider's location for an order.
-- REQUIRES      dispatch/delivery_dispatch.sql
--               delivery/delivery_summary.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   ordelo/wa_location.py (WaLocation) owns both tables:
--                   a customer or restaurant admin asks where the rider is -> wa_location_request (pending; coalesced with an open
--                   request for the same order/rider) -> one WhatsApp 'share your location' prompt to the rider
--                   -> the rider shares current location (WhatsApp: watomation/on_wa_location_handler.py; Telegram, R5:
--                      channels/telegram/rider/location.py) -> wa_location_observation
--                   -> every pending request for that order is fulfilled and routed to its callback_url (delivered).
--                 /wa-location-hooks routes (watomation/routers/wa_location_hooks.py) open requests; see docs/location_overview.md.
-- LIFECYCLE     wa_location_observation.source: whatsapp_current (WhatsApp "Share current location"), telegram_current (the rider
--                 bot's "Share current location" button, R5; wa_inbound_message_id holds 'tg:<chat>:<message>'), restaurant_confirmation
--                 (inferred at pickup). The callback to requesters keeps its two-value wire vocabulary: telegram_current is sent
--                 as 'whatsapp_current' ("rider's current GPS"; ordelo_datamodels/wa_location_pymodels.wire_source) until
--                 restaurant-agents accepts the new value.
--               wa_location_request.status: pending -> fulfilled -> delivered ; pending -> expired | failed
--               (wa_location_request_fulfilment_ck keeps observation_id / wa_location_res_time consistent with the status).
-- CALLED BY     wa_location_observation:
--                 python    ordelo/wa_location.py: WaLocation.observe_restaurant_confirmation(), WaLocation.receive_current_location(), WaLocation.request(), WaLocation.route_fulfilled_request()
--               wa_location_request:
--                 python    ordelo/wa_location.py: WaLocation._expire(), WaLocation._expire_pending_for_context(), WaLocation._fulfil(), WaLocation._mark_delivered(), WaLocation._mark_prompt_failed(), WaLocation._prompt_message_id(), WaLocation._request_status(), WaLocation._save_prompt_message_id(), +5 more
-- PYTHON MODEL  none
-- SECURITY      wa_location_observation: RLS ON; service role only (anon/authenticated revoked)
--               wa_location_request: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         tests/watomation/routers/test_wa_location_hooks.py
--               tests/sql/test_rider_telegram_r5_r6_migration_sql.py
--               tests/ordelo/test_wa_location.py
--               tests/channels/telegram/test_rider_location.py
-- GOTCHAS       wa_location_request_callback_url_length_ck is NOT VALID: older rows were never checked.
--               The trigger expire_wa_location_requests_on_inflight_delete in migrations/create_wa_location_tables.sql was never created live.
-- SEE ALSO      dispatch/delivery_inflight.sql
--               docs/location_overview.md
--               migrations/create_wa_location_tables.sql (history)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table wa_location_observation
--   One rider location received on demand (rider GPS share, or the restaurant location inferred at confirmation).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.wa_location_observation (
    observation_id uuid NOT NULL DEFAULT gen_random_uuid (),
    order_number character varying(100) NOT NULL,
    dispatch_id integer NOT NULL,
    rider_id character varying(12) NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    source character varying(40) NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    wa_inbound_message_id character varying(255),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT wa_location_observation_pkey PRIMARY KEY (observation_id),
    CONSTRAINT wa_location_observation_latitude_check CHECK (((latitude >= ('-90'::integer)::double precision) AND (latitude <= (90)::double precision))),
    CONSTRAINT wa_location_observation_longitude_check CHECK (((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision))),
    CONSTRAINT wa_location_observation_source_check CHECK (((source)::text = ANY ((ARRAY['whatsapp_current'::character varying, 'telegram_current'::character varying, 'restaurant_confirmation'::character varying])::text[]))),
    CONSTRAINT wa_location_observation_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES delivery_dispatch (dispatch_id) ON DELETE CASCADE,
    CONSTRAINT wa_location_observation_order_number_fkey FOREIGN KEY (order_number) REFERENCES delivery_summary (order_number) ON DELETE CASCADE
);

-- R5 (D50): the CHECK above for an existing table (CREATE TABLE IF NOT EXISTS does not change it).
ALTER TABLE public.wa_location_observation
    DROP CONSTRAINT IF EXISTS wa_location_observation_source_check;

ALTER TABLE public.wa_location_observation
    ADD CONSTRAINT wa_location_observation_source_check CHECK (((source)::text = ANY ((ARRAY['whatsapp_current'::character varying, 'telegram_current'::character varying, 'restaurant_confirmation'::character varying])::text[])));

CREATE UNIQUE INDEX IF NOT EXISTS wa_location_observation_inbound_message_uidx ON public.wa_location_observation USING btree (wa_inbound_message_id)
WHERE (wa_inbound_message_id IS NOT NULL);

CREATE INDEX IF NOT EXISTS wa_location_observation_order_observed_idx ON public.wa_location_observation USING btree (order_number, observed_at DESC);

CREATE INDEX IF NOT EXISTS wa_location_observation_rider_observed_idx ON public.wa_location_observation USING btree (rider_id, observed_at DESC);

ALTER TABLE public.wa_location_observation ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.wa_location_observation FROM anon, authenticated;

COMMENT ON TABLE public.wa_location_observation IS 'Point-in-time rider locations used by the on-demand WhatsApp WaLocation flow.';

COMMENT ON COLUMN public.wa_location_observation.source IS 'whatsapp_current / telegram_current are rider GPS; restaurant_confirmation is inferred and must be labelled last known at restaurant.';

-- ---------------------------------------------------------------------------------------------
-- table wa_location_request
--   One requester waiting for (or already sent) the rider's location for an order.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.wa_location_request (
    request_id uuid NOT NULL DEFAULT gen_random_uuid (),
    idempotency_key character varying(255),
    order_number character varying(100) NOT NULL,
    dispatch_id integer NOT NULL,
    rider_id character varying(12) NOT NULL,
    location_requested_by character varying(30) NOT NULL,
    requester_id character varying(50) NOT NULL,
    status character varying(20) NOT NULL DEFAULT 'pending' ::character varying,
    wa_location_req_time timestamp with time zone NOT NULL DEFAULT now(),
    wa_location_prompt_time timestamp with time zone,
    wa_location_res_time timestamp with time zone,
    wa_request_message_id character varying(255),
    observation_id uuid,
    route_attempt_count integer NOT NULL DEFAULT 0,
    last_route_attempt_time timestamp with time zone,
    route_error text,
    routed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    callback_url text,
    CONSTRAINT wa_location_request_pkey PRIMARY KEY (request_id),
    CONSTRAINT wa_location_request_delivery_ck CHECK (((((status)::text = 'delivered'::text) AND (routed_at IS NOT NULL)) OR ((status)::text <> 'delivered'::text))),
    CONSTRAINT wa_location_request_fulfilment_ck CHECK (((((status)::text = ANY ((ARRAY['fulfilled'::character varying, 'delivered'::character varying])::text[])) AND (observation_id IS NOT NULL) AND (wa_location_res_time IS NOT NULL)) OR (((status)::text = ANY ((ARRAY['pending'::character varying, 'failed'::character varying])::text[])) AND (observation_id IS NULL) AND (wa_location_res_time IS NULL)) OR (((status)::text = 'expired'::text) AND (((observation_id IS NULL) AND (wa_location_res_time IS NULL)) OR ((observation_id IS NOT NULL) AND (wa_location_res_time IS NOT NULL)))))),
    CONSTRAINT wa_location_request_location_requested_by_check CHECK (((location_requested_by)::text = ANY ((ARRAY['customer'::character varying, 'restaurant_admin'::character varying])::text[]))),
    CONSTRAINT wa_location_request_route_attempt_count_check CHECK ((route_attempt_count >= 0)),
    CONSTRAINT wa_location_request_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'fulfilled'::character varying, 'delivered'::character varying, 'expired'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT wa_location_request_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES delivery_dispatch (dispatch_id) ON DELETE CASCADE,
    CONSTRAINT wa_location_request_observation_id_fkey FOREIGN KEY (observation_id) REFERENCES wa_location_observation (observation_id) ON DELETE RESTRICT,
    CONSTRAINT wa_location_request_order_number_fkey FOREIGN KEY (order_number) REFERENCES delivery_summary (order_number) ON DELETE CASCADE
);

ALTER TABLE public.wa_location_request
    DROP CONSTRAINT IF EXISTS wa_location_request_callback_url_length_ck;

ALTER TABLE public.wa_location_request
    ADD CONSTRAINT wa_location_request_callback_url_length_ck CHECK (((callback_url IS NULL) OR (length(callback_url) <= 2048))) NOT VALID;

CREATE UNIQUE INDEX IF NOT EXISTS wa_location_request_idempotency_uidx ON public.wa_location_request USING btree (idempotency_key)
WHERE (idempotency_key IS NOT NULL);

CREATE INDEX IF NOT EXISTS wa_location_request_pending_order_idx ON public.wa_location_request USING btree (order_number, rider_id, wa_location_req_time)
WHERE ((status)::text = 'pending'::text);

CREATE INDEX IF NOT EXISTS wa_location_request_recent_prompt_idx ON public.wa_location_request USING btree (order_number, rider_id, wa_location_prompt_time DESC)
WHERE (((status)::text = 'pending'::text) AND (wa_location_prompt_time IS NOT NULL));

CREATE INDEX IF NOT EXISTS wa_location_request_unrouted_idx ON public.wa_location_request USING btree (status, last_route_attempt_time)
WHERE ((status)::text = 'fulfilled'::text);

ALTER TABLE public.wa_location_request ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.wa_location_request FROM anon, authenticated;

COMMENT ON TABLE public.wa_location_request IS 'One authorized requester/subscriber waiting for or delivered a WaLocation observation.';

COMMENT ON COLUMN public.wa_location_request.wa_location_req_time IS 'Time this caller requested the location.';

COMMENT ON COLUMN public.wa_location_request.wa_location_prompt_time IS 'Time an actual WhatsApp location prompt was sent; NULL for coalesced requests.';

COMMENT ON COLUMN public.wa_location_request.wa_location_res_time IS 'Time this request was paired with an observation.';
