-- Operator rollout. Verify the running audit uses restaurant selling prices
-- and the deployed frontend offers 5% for all six refs. Run the SELECT first,
-- and retain the output for rollback. A NULL key means the row was absent.
SELECT r.ref, c.config_key, c.config_value, c.description
FROM unnest(ARRAY['BNAT', 'CRDO', 'CRMS', 'ELAS', 'SFCS', 'STRK']) AS r(ref)
LEFT JOIN public.ordelo_config AS c
    ON c.config_key = r.ref || '_WEB_MAX_DISCOUNT_PERCENT'
ORDER BY r.ref;

BEGIN;
SET LOCAL lock_timeout = '5s';

INSERT INTO public.ordelo_config AS c (config_key, config_value, description)
SELECT ref || '_WEB_MAX_DISCOUNT_PERCENT', '5', 'Maximum advertised web discount for the nightly price audit'
FROM unnest(ARRAY['BNAT', 'CRDO', 'CRMS', 'ELAS', 'SFCS', 'STRK']) AS r(ref)
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = now()
WHERE c.config_value IS DISTINCT FROM EXCLUDED.config_value;

SELECT config_key, config_value
FROM public.ordelo_config
WHERE config_key IN (
    'BNAT_WEB_MAX_DISCOUNT_PERCENT', 'CRDO_WEB_MAX_DISCOUNT_PERCENT',
    'CRMS_WEB_MAX_DISCOUNT_PERCENT', 'ELAS_WEB_MAX_DISCOUNT_PERCENT',
    'SFCS_WEB_MAX_DISCOUNT_PERCENT', 'STRK_WEB_MAX_DISCOUNT_PERCENT'
)
ORDER BY config_key;

COMMIT;

-- Rollback: restore prior values from the preview. If a row was absent,
-- setting it to 0 restores the prior audit behavior without removing the row.
