-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/rest_admin_dashboard_alerts.sql
-- Restaurant dashboard "My alerts": the signed-in admin's own alert channels and their alert pause for this restaurant.
-- =============================================================================================
-- LIVE CHECK    Live since 19 Nov 2026 (applied with migrations/rest_admin_alerts_p1.sql; live body compared with this file). docs/adr/0018-restaurant-dashboard-settings-are-audited-and-enforced-at-order-creation.md.
-- OBJECTS       fn     rest_admin_alerts_get(p_session_id uuid) -> jsonb
--                   The signed-in admin's channels, Telegram link, current pause for this restaurant and the pause lengths.
--               fn     rest_admin_alerts_set_channels(p_session_id uuid, p_channels text[]) -> jsonb
--                   Change where the signed-in admin's alerts go (same rule as Telegram /channels).
--               fn     rest_admin_alerts_pause(p_session_id uuid, p_duration text) -> jsonb
--                   Pause the signed-in admin's alerts for this restaurant (same rule as Telegram /off).
--               fn     rest_admin_alerts_resume(p_session_id uuid) -> jsonb
--                   End that pause early (same rule as Telegram /on).
-- REQUIRES      restaurant_admin/admin_roster.sql (admin_set_channels, restaurant_admin)
--               availability/pauses.sql (pause_start, pause_end, pause_current, pause_options)
--               admin_dashboard/auth_sessions.sql (rest_admin_session_actor)
--               restaurant_admin/restaurant_settings.sql (restaurant_settings_audit)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE OR REPLACE.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   The dashboard twin of the restaurant bot's /channels (channels.py) and /off, /on (pauses.py): the same SQL
--                 rules decide (admin_set_channels; pause_start with the last-admin guard D52 and pause_end), so a change made
--                 in the dashboard is what the bot shows next, and the reverse. The person is the session's verified phone
--                 (rest_admin_session_actor); the browser sends no phone. Channels belong to the PERSON (every restaurant they
--                 admin); a pause belongs to the person AND this restaurant. Each change is written to restaurant_settings_audit
--                 (setting alert_channels / alert_pause, key = phone; not revertible by sys-admin: personal choices).
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 rest_admin_alerts_get:          ok | not_authorised
--                 rest_admin_alerts_set_channels: ok | bad_channels | not_found (no admin record: WhatsApp only, link Telegram
--                                                 first) | not_linked (Telegram chosen, no Telegram link) | not_authorised
--                 rest_admin_alerts_pause:        paused | extended | bad_duration | not_allowed (last unpaused admin) |
--                                                 not_admin | not_authorised
--                 rest_admin_alerts_resume:       resumed | not_paused | not_authorised
-- CALLED BY     all four:
--                 frontend  restaurant-frontend/lib/rest-admin-rpc.ts (app/api/rest-admin/settings/alerts/route.ts)
-- PYTHON MODEL  none
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated; granted to service_role.
-- TESTS         tests/sql/test_rest_admin_dashboard_alerts_sql.py
-- GOTCHAS       A pause stops NEW Telegram alerts only; WhatsApp admin alerts are unchanged (ADR 0013 Amendment 1).
--               pauses.created_via gained 'dashboard' (availability/pauses.sql).
-- SEE ALSO      channels/telegram/rest_admin/channels.py, channels/telegram/rest_admin/pauses.py, docs/adr/0013-*.md
-- =============================================================================================

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
