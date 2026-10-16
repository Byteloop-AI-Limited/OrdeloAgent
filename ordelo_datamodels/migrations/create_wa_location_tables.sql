-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Tables applied; the trigger expire_wa_location_requests_on_inflight_delete and its function are not live.
-- Current definitions now live in: rider_location/wa_location.sql
-- Purpose: On-demand WhatsApp rider-location tables.
-- The feature files above are the current truth; this file only records the one-off change.

-- Durable, on-demand WhatsApp rider-location requests.
-- This migration is intentionally not executed by application startup.

BEGIN;

CREATE TABLE public.wa_location_observation (
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number VARCHAR(100) NOT NULL
        REFERENCES public.delivery_summary(order_number) ON DELETE CASCADE,
    dispatch_id INTEGER NOT NULL
        REFERENCES public.delivery_dispatch(dispatch_id) ON DELETE CASCADE,
    rider_id VARCHAR(12) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    source VARCHAR(40) NOT NULL
        CHECK (source IN ('whatsapp_current', 'restaurant_confirmation')),
    observed_at TIMESTAMPTZ NOT NULL,
    wa_inbound_message_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX wa_location_observation_inbound_message_uidx
    ON public.wa_location_observation (wa_inbound_message_id)
    WHERE wa_inbound_message_id IS NOT NULL;

CREATE INDEX wa_location_observation_order_observed_idx
    ON public.wa_location_observation (order_number, observed_at DESC);

CREATE INDEX wa_location_observation_rider_observed_idx
    ON public.wa_location_observation (rider_id, observed_at DESC);

CREATE TABLE public.wa_location_request (
    request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255),
    order_number VARCHAR(100) NOT NULL
        REFERENCES public.delivery_summary(order_number) ON DELETE CASCADE,
    dispatch_id INTEGER NOT NULL
        REFERENCES public.delivery_dispatch(dispatch_id) ON DELETE CASCADE,
    rider_id VARCHAR(12) NOT NULL,
    location_requested_by VARCHAR(30) NOT NULL
        CHECK (location_requested_by IN ('customer', 'restaurant_admin')),
    requester_id VARCHAR(50) NOT NULL,
    callback_url TEXT NOT NULL CHECK (length(callback_url) <= 2048),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'fulfilled', 'delivered', 'expired', 'failed')),
    wa_location_req_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    wa_location_prompt_time TIMESTAMPTZ,
    wa_location_res_time TIMESTAMPTZ,
    wa_request_message_id VARCHAR(255),
    observation_id UUID
        REFERENCES public.wa_location_observation(observation_id) ON DELETE RESTRICT,
    route_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (route_attempt_count >= 0),
    last_route_attempt_time TIMESTAMPTZ,
    route_error TEXT,
    routed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT wa_location_request_fulfilment_ck CHECK (
        (
            status IN ('fulfilled', 'delivered')
            AND observation_id IS NOT NULL
            AND wa_location_res_time IS NOT NULL
        )
        OR (
            status IN ('pending', 'failed')
            AND observation_id IS NULL
            AND wa_location_res_time IS NULL
        )
        OR (
            status = 'expired'
            AND (
                (observation_id IS NULL AND wa_location_res_time IS NULL)
                OR (observation_id IS NOT NULL AND wa_location_res_time IS NOT NULL)
            )
        )
    ),
    CONSTRAINT wa_location_request_delivery_ck CHECK (
        (status = 'delivered' AND routed_at IS NOT NULL)
        OR status <> 'delivered'
    )
);

CREATE UNIQUE INDEX wa_location_request_idempotency_uidx
    ON public.wa_location_request (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX wa_location_request_pending_order_idx
    ON public.wa_location_request (order_number, rider_id, wa_location_req_time)
    WHERE status = 'pending';

CREATE INDEX wa_location_request_recent_prompt_idx
    ON public.wa_location_request (order_number, rider_id, wa_location_prompt_time DESC)
    WHERE status = 'pending' AND wa_location_prompt_time IS NOT NULL;

CREATE INDEX wa_location_request_unrouted_idx
    ON public.wa_location_request (status, last_route_attempt_time)
    WHERE status = 'fulfilled';

CREATE OR REPLACE FUNCTION public.expire_wa_location_requests_on_inflight_delete()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE public.wa_location_request
       SET status = 'expired',
           route_error = 'delivery_not_inflight',
           updated_at = now()
     WHERE order_number = OLD.order_number
       AND dispatch_id = OLD.dispatch_id
       AND rider_id = OLD.rider_id
       AND status IN ('pending', 'fulfilled');
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER expire_wa_location_requests_on_inflight_delete
AFTER DELETE ON public.delivery_inflight
FOR EACH ROW
EXECUTE FUNCTION public.expire_wa_location_requests_on_inflight_delete();

ALTER TABLE public.wa_location_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_location_request ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.wa_location_observation FROM anon, authenticated;
REVOKE ALL ON public.wa_location_request FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON public.wa_location_observation TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.wa_location_request TO service_role;

COMMENT ON TABLE public.wa_location_observation IS
    'Point-in-time rider locations for the on-demand WhatsApp WaLocation flow.';
COMMENT ON TABLE public.wa_location_request IS
    'One authorised requester/subscriber waiting for or delivered a WaLocation observation.';
COMMENT ON COLUMN public.wa_location_request.wa_location_prompt_time IS
    'Time an actual WhatsApp request_location prompt was sent; NULL for coalesced requests.';

COMMIT;
