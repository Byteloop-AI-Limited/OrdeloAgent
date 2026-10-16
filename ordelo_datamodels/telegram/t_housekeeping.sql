-- ---------------------------------------------------------------------------------------------
-- 12. t_housekeeping(): daily purge (D22). Returns jsonb counts. Retention comes from ordelo_config.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_housekeeping ()
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_inbox_days int;
    v_ledger_days int;
    n_inbox int;
    n_ledger int;
    n_alerts int;
BEGIN
    SELECT
        COALESCE((
            SELECT
                config_value::int
            FROM public.ordelo_config
            WHERE
                config_key = 'TGRAM_INBOX_RETENTION_DAYS'
                AND config_value ~ '^\s*\d+\s*$'), 7) INTO v_inbox_days;
    SELECT
        COALESCE((
            SELECT
                config_value::int
            FROM public.ordelo_config
            WHERE
                config_key = 'TGRAM_LEDGER_RETENTION_DAYS'
                AND config_value ~ '^\s*\d+\s*$'), 30) INTO v_ledger_days;

    DELETE FROM public.t_inbox
    WHERE received_at < now() - make_interval(days => v_inbox_days);
    GET DIAGNOSTICS n_inbox = ROW_COUNT;
    DELETE FROM public.t_sent_messages
    WHERE state = 'closed'
        AND closed_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_ledger = ROW_COUNT;
    DELETE FROM public.t_order_alerts
    WHERE status <> 'pending'
        AND created_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_alerts = ROW_COUNT;

    RETURN jsonb_build_object('t_inbox', n_inbox, 't_sent_messages', n_ledger, 't_order_alerts', n_alerts);
END
$$;

REVOKE ALL ON FUNCTION public.t_housekeeping () FROM PUBLIC, anon, authenticated;
