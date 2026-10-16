-- =============================================================================================
-- ordelo_datamodels/payment/record_payment_authorised.sql
-- Apply a payment authorisation to an order at most once (requires_payment -> requires_capture).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     record_payment_authorised(p_provider_event_id text, p_order_id text, p_payment_intent_id text, p_amount_pence integer, p_payload jsonb) -> jsonb
--                   Record an authorisation event and move the order to 'requires_capture', once.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call writes one payment_event row and may update one food_order row.
-- HOW IT FITS   Payment callback -> utils_common/payment_ms/payment_events.py -> record_payment_authorised()
--                   -> 'applied': food_order.payment_status = 'requires_capture'; the caller then starts fulfilment
--                      (/payment-hooks/payment-complete -> init_delivery / init_takeaway).
--                   -> 'duplicate': the provider_event_id was seen before; nothing changes.
--                   -> 'rejected_state': the order is not 'requires_payment' (logged as payment_event 'rejected_state').
--                   -> 'unknown_order': no such order_id.
-- LIFECYCLE     food_order.payment_status: requires_payment --(this function)--> requires_capture; capture/cancel happen later in Python.
-- CALLED BY     record_payment_authorised:
--                 python    utils_common/payment_ms/payment_events.py: record_payment_authorised()
-- PYTHON MODEL  none
-- SECURITY      record_payment_authorised(): executable by PUBLIC (default)
-- TESTS         tests/utils_common/payment_ms/test_payment_events.py
--               tests/watomation/routers/test_payment_hooks.py
-- GOTCHAS       Authorisation holds funds; capture charges them later. 'requires_capture' is not proof of capture.
-- SEE ALSO      payment/payment_event.sql
--               docs/payment_and_order_flow.md
--               docs/web-ordering-playground.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function record_payment_authorised(p_provider_event_id text, p_order_id text, p_payment_intent_id text, p_amount_pence integer, p_payload jsonb) -> jsonb
--   Record an authorisation event and move the order to 'requires_capture', once.
--   Returns {"outcome": "applied", "order": {...}} | {"outcome": "duplicate"} |
--           {"outcome": "rejected_state", "payment_status": ...} | {"outcome": "unknown_order"}.
--   Event id and order id are required (RAISE otherwise).
--   Data: writes food_order, payment_event.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.record_payment_authorised (p_provider_event_id text, p_order_id text, p_payment_intent_id text DEFAULT NULL, p_amount_pence integer DEFAULT NULL, p_payload jsonb DEFAULT '{}' ::jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_order public.food_order%ROWTYPE;
    v_status text;
    v_new_id bigint;
BEGIN
    IF p_provider_event_id IS NULL OR p_order_id IS NULL THEN
        RAISE EXCEPTION 'record_payment_authorised: event id and order id are required';
    END IF;

    IF NOT EXISTS (
        SELECT
            1
        FROM
            public.food_order
        WHERE
            order_id = p_order_id) THEN
    RETURN jsonb_build_object('outcome', 'unknown_order');
END IF;

INSERT INTO public.payment_event (provider_event_id, order_id, kind, payment_intent_id, amount_pence, payload)
    VALUES (p_provider_event_id, p_order_id, 'authorised', p_payment_intent_id, p_amount_pence, COALESCE(p_payload, '{}'::jsonb))
ON CONFLICT (provider_event_id)
    DO NOTHING
RETURNING
    id INTO v_new_id;

    IF v_new_id IS NULL THEN
        INSERT INTO public.payment_event (provider_event_id, order_id, kind, payload)
            VALUES ('ordelo:authorised_duplicate:' || p_order_id || ':' || gen_random_uuid (), p_order_id, 'authorised_duplicate', jsonb_build_object('original_event_id', p_provider_event_id));
        RETURN jsonb_build_object('outcome', 'duplicate');
    END IF;

    UPDATE
        public.food_order
    SET
        payment_status = 'requires_capture'
    WHERE
        order_id = p_order_id
        AND payment_status = 'requires_payment'
    RETURNING
        * INTO v_order;

    IF NOT FOUND THEN
        SELECT
            payment_status INTO v_status
        FROM
            public.food_order
        WHERE
            order_id = p_order_id;
        UPDATE
            public.payment_event
        SET
            kind = 'rejected_state'
        WHERE
            id = v_new_id;
        RETURN jsonb_build_object('outcome', 'rejected_state', 'payment_status', v_status);
    END IF;

    RETURN jsonb_build_object('outcome', 'applied', 'order', to_jsonb (v_order));
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.record_payment_authorised (p_provider_event_id text, p_order_id text, p_payment_intent_id text, p_amount_pence integer, p_payload jsonb) IS 'Record an authorisation event and move the order to ''requires_capture'', once.';
