-- ---------------------------------------------------------------------------
-- R1a  M2: apply a payment authorisation at most once
-- ---------------------------------------------------------------------------
-- Returns {"outcome": "applied", "order": {...food_order row...}}
--      or {"outcome": "duplicate"}                (same event seen before)
--      or {"outcome": "rejected_state", "payment_status": "..."}  (not requires_payment)
--      or {"outcome": "unknown_order"}            (no such order_id)
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
