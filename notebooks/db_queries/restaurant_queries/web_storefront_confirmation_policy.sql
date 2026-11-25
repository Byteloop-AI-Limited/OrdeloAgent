-- Operator rollout. Run the preview SELECT first and keep its output for rollback.
-- Run the transaction only in the agreed quiet window after checking staff coverage
-- and effective Telegram reminder offsets (all should be below 120 seconds).
SELECT r.rest_ref, r.auto_accept, p.timeout_minutes, p.timeout_action,
       c.config_key, c.config_value, c.description
FROM public.restaurant_master AS r
CROSS JOIN LATERAL public.restaurant_confirmation_policy(r.rest_ref::text) AS p
LEFT JOIN public.ordelo_config AS c ON c.config_key IN (
    r.rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME',
    r.rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION',
    r.rest_ref || '_TGRAM_ORDER_ALERT_OFFSETS_SECS'
)
WHERE r.rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
ORDER BY r.rest_ref, c.config_key;

BEGIN;
SET LOCAL lock_timeout = '5s';

DO $$
BEGIN
    PERFORM 1 FROM public.restaurant_master
    WHERE rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
    ORDER BY rest_ref FOR UPDATE;
    IF (SELECT count(*) FROM public.restaurant_master
        WHERE rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')) <> 4 THEN
        RAISE EXCEPTION 'Expected all four restaurant records';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.delivery_summary
        WHERE rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
          AND restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
          AND pickup_time IS NULL
        UNION ALL
        SELECT 1 FROM public.takeaway_summary
        WHERE rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
          AND restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
          AND pickup_time IS NULL
    ) THEN
        RAISE EXCEPTION 'Wait for outstanding confirmations and pickup selections';
    END IF;
    IF EXISTS (
        SELECT 1 FROM (VALUES ('delivery'), ('takeaway')) AS k(kind)
        CROSS JOIN LATERAL public.restaurant_default_pickup_minutes('BNAT', k.kind) AS d
        WHERE d.minutes IS NULL
    ) THEN
        RAISE EXCEPTION 'Burger Nation needs valid pickup defaults for both modes';
    END IF;

    PERFORM public.restaurant_setting_change(
        r.rest_ref, 'auto_accept', NULL, to_jsonb(r.rest_ref = 'BNAT'),
        'operator', 'operator', NULL
    )
    FROM public.restaurant_master AS r
    WHERE r.rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
    ORDER BY r.rest_ref;
END;
$$;

INSERT INTO public.ordelo_config AS c (config_key, config_value, description)
SELECT ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_' || suffix, val, description
FROM unnest(ARRAY['CRDO', 'CRMS', 'STRK']) AS refs(ref)
CROSS JOIN (VALUES
    ('TIME', '2', 'Minutes before an unanswered restaurant confirmation becomes eligible for the timeout sweep'),
    ('ACTION', 'decline', 'Decline an unanswered restaurant confirmation on timeout')
) AS settings(suffix, val, description)
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = now()
WHERE c.config_value IS DISTINCT FROM EXCLUDED.config_value;

-- Expect BNAT true and the other three false, 2, decline.
SELECT r.rest_ref, r.auto_accept, p.timeout_minutes, p.timeout_action
FROM public.restaurant_master AS r
CROSS JOIN LATERAL public.restaurant_confirmation_policy(r.rest_ref::text) AS p
WHERE r.rest_ref IN ('BNAT', 'CRDO', 'CRMS', 'STRK')
ORDER BY r.rest_ref;

COMMIT;

-- Rollback in a quiet window: use restaurant_setting_revert with the audit IDs
-- created by this run and restore prior timeout values from the preview.
-- Restore absent timeout rows to absence through a separately approved deletion.
