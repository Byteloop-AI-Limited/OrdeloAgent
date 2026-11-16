-- Web-only restaurants (STRK, CRDO, CRMS, BNAT): silence means DECLINE, a longer answer time, more admin reminders.
-- Plan: plans/restaurant-confirmation-timeout-action-plan.md.   Run block by block in the Supabase SQL editor.
-- ORDER: 1) apply ordelo_datamodels/migrations/restaurant_confirmation_timeout_action.sql  2) deploy the code
--        3) CRDO and BNAT: confirm their admins are linked on Telegram (block A)  4) block B (the switch)  5) block C (verify).
-- Rollback = block R (instant; nothing else to undo).

-- A. PREFLIGHT (read only). Every restaurant below needs at least one linked Telegram admin before it is switched,
--    otherwise nobody sees the Accept / Decline card and every order will be auto-declined.
SELECT r.rest_ref, r.admins,
       (SELECT count(*) FROM public.t_invites i WHERE i.rest_ref = r.rest_ref AND i.status = 'claimed') AS linked_telegram_admins
FROM public.restaurant_master r WHERE r.rest_ref IN ('STRK', 'CRDO', 'CRMS', 'BNAT') ORDER BY 1;

-- Current values (copy this result somewhere before block B: it is your rollback record).
SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key ~ '^(STRK|CRDO|CRMS|BNAT)_(RESTAURANT_CONFIRMATION_TIMEOUT_(TIME|ACTION)|TGRAM_ORDER_ALERT_OFFSETS_SECS)$' ORDER BY 1;

-- B. THE SWITCH. 3 minutes to answer; card re-sent at 15 s, then every 30 s, last one 10 s before the deadline.
INSERT INTO public.ordelo_config (config_key, config_value, description)
SELECT r || '_' || k.suffix, k.val, k.descr
FROM unnest(ARRAY['STRK', 'CRDO', 'CRMS', 'BNAT']) AS r,
     (VALUES
        ('RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '3',
         'Minutes since order creation before an unanswered confirmation is decided by the timeout action (accepted orders without a pickup time are always auto-accepted); checked every 10 seconds'),
        ('RESTAURANT_CONFIRMATION_TIMEOUT_ACTION', 'decline',
         'What silence means when the confirmation times out: decline = order declined (auto_decline, customer told, payment cancelled); anything else or no row = auto-accepted (restaurant_timedout)'),
        ('TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45,60,90,120,150,170',
         'Seconds after order creation to send or refresh the Telegram admin order card while confirmation is unanswered; keep the last offset below the timeout')
     ) AS k(suffix, val, descr)
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, description = EXCLUDED.description, updated_at = CURRENT_TIMESTAMP;

-- C. VERIFY (read only). Expect timeout_minutes 3 and timeout_action decline for all four.
SELECT r AS rest_ref, p.* FROM unnest(ARRAY['STRK', 'CRDO', 'CRMS', 'BNAT']) AS r, LATERAL public.restaurant_confirmation_policy(r) p;

-- R. ROLLBACK: silence is accepted again (the other values can stay; put back the old ones from block A if you want them).
-- UPDATE public.ordelo_config SET config_value = 'accept', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key IN ('STRK_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION', 'CRDO_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION',
--                      'CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION', 'BNAT_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION');
