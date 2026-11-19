-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-11-19 (agent, owner-authorised implementation run, during the owner's verification window)
-- Current definitions now live in: restaurant_admin/rest_admin_dashboard_alerts.sql; availability/pauses.sql (CHECK)
-- Purpose: docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md: restaurant dashboard "My alerts" (channels, pause).
--          pauses.created_via also accepts 'dashboard' (CHECK relaxed, never narrowed). Additive functions only.
-- VERIFY:  SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'pauses_created_via_check';  -- has dashboard
-- Then:    python scripts/datamodels/drift_check.py

ALTER TABLE public.pauses DROP CONSTRAINT IF EXISTS pauses_created_via_check;
ALTER TABLE public.pauses ADD CONSTRAINT pauses_created_via_check
    CHECK ((created_via = ANY (ARRAY['telegram'::text, 'whatsapp'::text, 'operator'::text, 'dashboard'::text])));

CREATE OR REPLACE FUNCTION public.rest_admin_alerts_get (p_session_id uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    ra restaurant_admin%ROWTYPE;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    SELECT * INTO ra FROM restaurant_admin WHERE phone = a.phone;
    RETURN jsonb_build_object(
        'result', 'ok', 'rest_ref', a.rest_ref,
        'channels', to_jsonb(coalesce(ra.channels, ARRAY['whatsapp']::text[])),
        'telegram_linked', ra.tuid IS NOT NULL,
        'pause', pause_current ('rest_admin', a.phone, a.rest_ref),
        'pause_options', pause_options ('rest_admin'));
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_alerts_set_channels (p_session_id uuid, p_channels text[])
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_old text[];
    v_out jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    SELECT channels INTO v_old FROM restaurant_admin WHERE phone = a.phone;
    v_out := admin_set_channels (a.phone, p_channels, 'dashboard');
    IF v_out ->> 'result' = 'ok' AND to_jsonb(v_old) IS DISTINCT FROM v_out -> 'channels' THEN
        INSERT INTO restaurant_settings_audit (rest_ref, setting, setting_key, old_value, new_value, by_who, via, session_id)
            VALUES (a.rest_ref, 'alert_channels', a.phone, to_jsonb(v_old), v_out -> 'channels', a.phone, 'dashboard', p_session_id);
    END IF;
    RETURN v_out;
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_alerts_pause (p_session_id uuid, p_duration text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_out jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_out := pause_start ('rest_admin', a.phone, a.rest_ref, p_duration, 'dashboard', a.phone);
    IF v_out ->> 'result' IN ('paused', 'extended') THEN
        INSERT INTO restaurant_settings_audit (rest_ref, setting, setting_key, old_value, new_value, by_who, via, session_id)
            VALUES (a.rest_ref, 'alert_pause', a.phone, NULL, jsonb_build_object('until', v_out -> 'ends_at'), a.phone,
                    'dashboard', p_session_id);
    END IF;
    RETURN v_out;
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_alerts_resume (p_session_id uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_out jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    v_out := pause_end ('rest_admin', a.phone, a.rest_ref, 'resumed');
    IF v_out ->> 'result' = 'resumed' THEN
        INSERT INTO restaurant_settings_audit (rest_ref, setting, setting_key, old_value, new_value, by_who, via, session_id)
            VALUES (a.rest_ref, 'alert_pause', a.phone, NULL, 'null'::jsonb, a.phone, 'dashboard', p_session_id);
    END IF;
    RETURN v_out;
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

REVOKE ALL ON FUNCTION public.rest_admin_alerts_get (uuid), public.rest_admin_alerts_set_channels (uuid, text[]),
    public.rest_admin_alerts_pause (uuid, text), public.rest_admin_alerts_resume (uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rest_admin_alerts_get (uuid), public.rest_admin_alerts_set_channels (uuid, text[]),
    public.rest_admin_alerts_pause (uuid, text), public.rest_admin_alerts_resume (uuid) TO service_role;
