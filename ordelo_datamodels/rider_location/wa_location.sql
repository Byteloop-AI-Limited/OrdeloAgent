-- BEGIN;

CREATE TABLE public.wa_location_observation (
    observation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number VARCHAR(100) NOT NULL
        REFERENCES public.delivery_summary(order_number) ON DELETE CASCADE,
    dispatch_id INTEGER NOT NULL
        REFERENCES public.delivery_dispatch(dispatch_id) ON DELETE CASCADE,
    rider_id VARCHAR(12) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL
        CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL
        CHECK (longitude BETWEEN -180 AND 180),
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
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'fulfilled', 'delivered', 'expired', 'failed')),
    wa_location_req_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    wa_location_prompt_time TIMESTAMPTZ,
    wa_location_res_time TIMESTAMPTZ,
    wa_request_message_id VARCHAR(255),
    observation_id UUID
        REFERENCES public.wa_location_observation(observation_id) ON DELETE RESTRICT,
    route_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (route_attempt_count >= 0),
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
        OR
        (
            status IN ('pending', 'failed')
            AND observation_id IS NULL
            AND wa_location_res_time IS NULL
        )
        OR
        (
            status = 'expired'
            AND (
                (observation_id IS NULL AND wa_location_res_time IS NULL)
                OR
                (observation_id IS NOT NULL AND wa_location_res_time IS NOT NULL)
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

ALTER TABLE public.wa_location_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wa_location_request ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.wa_location_observation FROM anon, authenticated;
REVOKE ALL ON public.wa_location_request FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON public.wa_location_observation TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.wa_location_request TO service_role;

COMMENT ON TABLE public.wa_location_observation IS
    'Point-in-time rider locations used by the on-demand WhatsApp WaLocation flow.';
COMMENT ON COLUMN public.wa_location_observation.source IS
    'whatsapp_current is rider GPS; restaurant_confirmation is inferred and must be labelled last known at restaurant.';
COMMENT ON TABLE public.wa_location_request IS
    'One authorized requester/subscriber waiting for or delivered a WaLocation observation.';
COMMENT ON COLUMN public.wa_location_request.wa_location_req_time IS
    'Time this caller requested the location.';
COMMENT ON COLUMN public.wa_location_request.wa_location_prompt_time IS
    'Time an actual WhatsApp location prompt was sent; NULL for coalesced requests.';
COMMENT ON COLUMN public.wa_location_request.wa_location_res_time IS
    'Time this request was paired with an observation.';

-- COMMIT;
-- 

ALTER TABLE public.wa_location_request
    ADD COLUMN IF NOT EXISTS callback_url TEXT;

ALTER TABLE public.wa_location_request
    ADD CONSTRAINT wa_location_request_callback_url_length_ck
    CHECK (callback_url IS NULL OR length(callback_url) <= 2048)
    NOT VALID;
    


