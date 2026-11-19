-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-11-19 (agent, during the owner's verification window; owner-authorised implementation run)
-- Current definitions now live in: restaurant_admin/admin_roster.sql (is_overwatch, t_admin_link, t_admin_profile,
--   admin_unlink_telegram); admin_dashboard/auth_sessions.sql (portal access, admin mints, admin sessions, revocation)
-- Purpose: portal links and dashboard sessions, docs/adr/0017-portal-access-is-decided-per-request-in-sql.md.
--   . overwatch phones can link to the restaurant bot with no restaurant (t_admin_link / t_admin_profile 'ops_only')
--   . relink to another Telegram account / unlink revokes the phone's rest_admin + sys_admin sessions and unused links
--   . portal_access(), rest_admin_dashboard_mint(), sys_admin_dashboard_mint(): issuance with the authority check and the
--     insert in one transaction (Telegram actor by tuid, WhatsApp actor by phone)
--   . admin_dashboard_activate() / admin_dashboard_touch(): GET-safe activation and per-request re-check of roster /
--     overwatch membership for the restaurant-frontend admin dashboards
--   . rest_admin_session_actor(): the session-bound actor for every restaurant-dashboard settings RPC
-- Compatibility: additive functions; the changed t_admin_* bodies keep every existing result value (new: 'ops_only' and
--   the 'sys_admin' field). Deployed code that does not know them treats an ops-only person as not linked.
-- Requires: restaurant_admin/admin_roster.sql P1 (live), admin_dashboard/auth_sessions.sql table (live).
-- VERIFY:  SELECT is_overwatch('<an overwatch phone>'), portal_access(NULL, '447700900999')->>'result';  -- true, ok
-- Then:    python scripts/datamodels/drift_check.py
-- No COMMENT ON statements here (Gate 2: catalogue comments need owner approval).

CREATE OR REPLACE FUNCTION public.is_overwatch (p_phone text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        public.admin_phone_digits (p_phone) IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM public.ordelo_config c
            CROSS JOIN LATERAL unnest(string_to_array(c.config_value, ',')) AS e (raw)
            WHERE c.config_key = 'overwatch_list'
              AND public.admin_phone_digits (e.raw) = public.admin_phone_digits (p_phone))
$$;

REVOKE ALL ON FUNCTION public.is_overwatch (text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.is_overwatch (text) TO service_role;

CREATE OR REPLACE FUNCTION public.t_admin_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_phone text := admin_phone_digits (p_phone);
    v_row restaurant_admin%ROWTYPE;
    v_other text;
    v_result text;
    v_prev_tuid bigint;
    v_prev_username text;
BEGIN
    IF v_phone IS NULL OR p_tuid IS NULL OR p_tcid IS NULL THEN
        RETURN jsonb_build_object('result', 'bad_phone');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM admin_roster r WHERE r.phone = v_phone) AND NOT is_overwatch (v_phone) THEN
        RETURN jsonb_build_object('result', 'not_on_roster');
    END IF;
    SELECT phone INTO v_other FROM restaurant_admin WHERE tuid = p_tuid AND phone <> v_phone;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'tuid_taken', 'phone_last4', RIGHT (v_other, 4));
    END IF;
    INSERT INTO restaurant_admin (phone) VALUES (v_phone) ON CONFLICT (phone) DO NOTHING;
    SELECT * INTO v_row FROM restaurant_admin WHERE phone = v_phone FOR UPDATE;
    IF v_row.tuid IS NULL THEN
        UPDATE restaurant_admin
        SET tuid = p_tuid, tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, t_linked_at = now(),
            channels = ARRAY['telegram']::text[], channels_set_by = 'link', updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'linked';
    ELSIF v_row.tuid = p_tuid THEN
        UPDATE restaurant_admin
        SET tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'already_linked';
    ELSE
        v_prev_tuid := v_row.tuid;
        v_prev_username := v_row.t_username;
        UPDATE restaurant_admin
        SET tuid = p_tuid, tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, t_linked_at = now(),
            updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'relinked';
        PERFORM auth_sessions_revoke_phone (v_phone, 'relinked');
    END IF;
    RETURN jsonb_build_object(
        'result', v_result, 'phone', v_row.phone, 'channels', to_jsonb(v_row.channels),
        'restaurants', (SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name)
                                                  ORDER BY r.rest_ref), '[]'::jsonb)
                          FROM admin_roster r WHERE r.phone = v_phone),
        'sys_admin', is_overwatch (v_phone),
        'previous_tuid', v_prev_tuid, 'previous_username', v_prev_username);
EXCEPTION
    WHEN unique_violation THEN
        RETURN jsonb_build_object('result', 'tuid_taken');
END;
$$;

REVOKE ALL ON FUNCTION public.t_admin_link (bigint, bigint, text, text, text) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.t_admin_profile (p_tuid bigint)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        CASE WHEN ra.phone IS NULL THEN
            jsonb_build_object('result', 'not_linked')
        ELSE
            jsonb_build_object(
                'result', CASE WHEN EXISTS (SELECT 1 FROM admin_roster r WHERE r.phone = ra.phone) THEN 'ok'
                               WHEN is_overwatch (ra.phone) THEN 'ops_only'
                               ELSE 'not_on_roster' END,
                'phone', ra.phone, 'channels', to_jsonb(ra.channels), 't_first_name', ra.t_first_name,
                'sys_admin', is_overwatch (ra.phone),
                'restaurants', (SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name)
                                                          ORDER BY r.rest_ref), '[]'::jsonb)
                                  FROM admin_roster r WHERE r.phone = ra.phone))
        END
    FROM (SELECT 1) one
    LEFT JOIN restaurant_admin ra ON ra.tuid = p_tuid
$$;

REVOKE ALL ON FUNCTION public.t_admin_profile (bigint) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.admin_unlink_telegram (p_phone text, p_by text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_row restaurant_admin%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM restaurant_admin WHERE phone = admin_phone_digits (p_phone) FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    ELSIF v_row.tuid IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    UPDATE restaurant_admin
    SET tuid = NULL, tcid = NULL, t_username = NULL, t_first_name = NULL, t_linked_at = NULL,
        channels = ARRAY['whatsapp']::text[], channels_set_by = p_by, updated_at = now()
    WHERE phone = v_row.phone;
    PERFORM auth_sessions_revoke_phone (v_row.phone, 'unlinked');
    RETURN jsonb_build_object('result', 'ok');
END;
$$;

REVOKE ALL ON FUNCTION public.admin_unlink_telegram (text, text) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.auth_sessions_revoke_phone (p_phone text, p_reason text)
    RETURNS integer
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_n integer;
BEGIN
    UPDATE auth_sessions
    SET revoked = TRUE, revoked_at = clock_timestamp(), revoked_reason = p_reason
    WHERE principal_id = admin_phone_digits (p_phone)
      AND ROLE IN ('rest_admin', 'sys_admin')
      AND NOT revoked;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n;
END;
$$;

CREATE OR REPLACE FUNCTION public.admin_actor_phone (p_tuid bigint, p_phone text)
    RETURNS text
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_phone text;
BEGIN
    IF (p_tuid IS NULL) = (p_phone IS NULL) THEN
        RAISE EXCEPTION 'exactly one of p_tuid and p_phone'
            USING ERRCODE = '22023';
    END IF;
    IF p_tuid IS NOT NULL THEN
        SELECT phone INTO v_phone FROM restaurant_admin WHERE tuid = p_tuid FOR UPDATE;
        RETURN v_phone;
    END IF;
    v_phone := admin_phone_digits (p_phone);
    PERFORM 1 FROM restaurant_admin WHERE phone = v_phone FOR UPDATE;
    RETURN v_phone;
END;
$$;

CREATE OR REPLACE FUNCTION public.admin_session_authorised (p_role text, p_principal text, p_scope text)
    RETURNS boolean
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
BEGIN
    RETURN CASE p_role
        WHEN 'rest_admin' THEN EXISTS (SELECT 1 FROM admin_roster r WHERE r.phone = p_principal AND r.rest_ref = p_scope)
        WHEN 'sys_admin' THEN coalesce(is_overwatch (p_principal), FALSE)
        ELSE FALSE
    END;
END;
$$;

CREATE OR REPLACE FUNCTION public.portal_access (p_tuid bigint, p_phone text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_phone text;
BEGIN
    IF (p_tuid IS NULL) = (p_phone IS NULL) THEN
        RAISE EXCEPTION 'exactly one of p_tuid and p_phone'
            USING ERRCODE = '22023';
    END IF;
    IF p_tuid IS NOT NULL THEN
        SELECT phone INTO v_phone FROM restaurant_admin WHERE tuid = p_tuid;
    ELSE
        v_phone := admin_phone_digits (p_phone);
    END IF;
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    RETURN jsonb_build_object(
        'result', 'ok', 'phone', v_phone, 'sys_admin', is_overwatch (v_phone),
        'restaurants', (SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name)
                                                  ORDER BY r.rest_ref), '[]'::jsonb)
                          FROM admin_roster r WHERE r.phone = v_phone));
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_dashboard_mint (p_tuid bigint, p_phone text, p_rest_ref text, p_token_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_phone text;
    v_ref text := upper(p_rest_ref);
    n timestamptz;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'invalid token hash'
            USING ERRCODE = '22023';
    END IF;
    v_phone := admin_actor_phone (p_tuid, p_phone);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    IF NOT admin_session_authorised ('rest_admin', v_phone, v_ref) THEN
        RETURN jsonb_build_object('result', 'not_allowed');
    END IF;
    n := clock_timestamp();
    INSERT INTO auth_sessions (ROLE, principal_id, scope_ref, wa_number, token_hash, created_at, expires_at)
        VALUES ('rest_admin', v_phone, v_ref, v_phone, p_token_hash, n, n + interval '30 minutes');
    RETURN jsonb_build_object('result', 'ok');
END;
$$;

CREATE OR REPLACE FUNCTION public.sys_admin_dashboard_mint (p_tuid bigint, p_phone text, p_token_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_phone text;
    n timestamptz;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'invalid token hash'
            USING ERRCODE = '22023';
    END IF;
    v_phone := admin_actor_phone (p_tuid, p_phone);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    IF NOT admin_session_authorised ('sys_admin', v_phone, NULL) THEN
        RETURN jsonb_build_object('result', 'not_allowed');
    END IF;
    n := clock_timestamp();
    INSERT INTO auth_sessions (ROLE, principal_id, scope_ref, wa_number, token_hash, created_at, expires_at)
        VALUES ('sys_admin', v_phone, NULL, v_phone, p_token_hash, n, n + interval '30 minutes');
    RETURN jsonb_build_object('result', 'ok');
END;
$$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_activate (p_role text, p_token_hash text, p_cookie_hash text,
    p_ua_hash text, p_ip text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    s auth_sessions%ROWTYPE;
    n timestamptz := clock_timestamp();
BEGIN
    IF p_role NOT IN ('rest_admin', 'sys_admin') OR p_token_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$'
        OR p_cookie_hash IS NULL OR p_cookie_hash !~ '^[a-f0-9]{64}$' OR p_ua_hash IS NULL OR p_ua_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'not_found');
    END IF;
    SELECT * INTO s FROM auth_sessions WHERE token_hash = p_token_hash AND ROLE = p_role FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'not_found');
    ELSIF s.revoked THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'revoked');
    ELSIF s.activated_at IS NOT NULL THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'already_used');
    ELSIF s.expires_at <= n THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'expired');
    ELSIF NOT admin_session_authorised (s.role, s.principal_id, s.scope_ref) THEN
        UPDATE auth_sessions SET revoked = TRUE, revoked_at = n, revoked_reason = 'not_authorised' WHERE id = s.id;
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'not_authorised');
    END IF;
    UPDATE auth_sessions
    SET token_hash = NULL, cookie_hash = p_cookie_hash, activated_at = n, last_seen_at = n,
        hard_expires_at = n + interval '4 hours', bound_ua_hash = p_ua_hash,
        bound_ip = CASE WHEN p_ip ~ '^[0-9a-fA-F:.]+$' THEN p_ip::inet END
    WHERE id = s.id;
    RETURN jsonb_build_object('result', 'ok', 'session_id', s.id);
END;
$$;

CREATE OR REPLACE FUNCTION public.admin_dashboard_touch (p_role text, p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    s auth_sessions%ROWTYPE;
    n timestamptz := clock_timestamp();
BEGIN
    IF p_role NOT IN ('rest_admin', 'sys_admin') OR p_cookie_hash IS NULL OR p_cookie_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'no_session');
    END IF;
    SELECT * INTO s FROM auth_sessions WHERE cookie_hash = p_cookie_hash AND ROLE = p_role;
    IF NOT FOUND OR s.activated_at IS NULL THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'no_session');
    ELSIF s.revoked THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'revoked');
    ELSIF s.bound_ua_hash IS DISTINCT FROM p_ua_hash THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'ua_mismatch');
    ELSIF s.hard_expires_at IS NULL OR s.hard_expires_at <= n THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'hard_cap');
    ELSIF s.last_seen_at IS NULL OR s.last_seen_at <= n - interval '60 minutes' THEN
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'idle');
    ELSIF NOT admin_session_authorised (s.role, s.principal_id, s.scope_ref) THEN
        UPDATE auth_sessions SET revoked = TRUE, revoked_at = n, revoked_reason = 'not_authorised' WHERE id = s.id;
        RETURN jsonb_build_object('result', 'invalid', 'reason', 'not_authorised');
    END IF;
    UPDATE auth_sessions SET last_seen_at = n WHERE id = s.id AND NOT revoked;
    RETURN jsonb_build_object('result', 'ok', 'session_id', s.id, 'principal_id', s.principal_id,
        'scope_ref', s.scope_ref, 'wa_number', s.wa_number);
END;
$$;

CREATE OR REPLACE FUNCTION public.rest_admin_session_actor (p_session_id uuid, OUT phone text, OUT rest_ref text)
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    s auth_sessions%ROWTYPE;
BEGIN
    SELECT * INTO s FROM auth_sessions WHERE id = p_session_id;
    IF NOT FOUND OR s.role <> 'rest_admin' OR s.revoked OR s.activated_at IS NULL OR s.hard_expires_at <= now()
        OR s.last_seen_at <= now() - interval '60 minutes'
        OR NOT admin_session_authorised ('rest_admin', s.principal_id, s.scope_ref) THEN
        RAISE EXCEPTION 'not_authorised'
            USING ERRCODE = '28000';
    END IF;
    phone := s.principal_id;
    rest_ref := s.scope_ref;
END;
$$;

REVOKE ALL ON FUNCTION public.auth_sessions_revoke_phone (text, text), public.admin_actor_phone (bigint, text),
    public.admin_session_authorised (text, text, text), public.portal_access (bigint, text),
    public.rest_admin_dashboard_mint (bigint, text, text, text), public.sys_admin_dashboard_mint (bigint, text, text),
    public.admin_dashboard_activate (text, text, text, text, text), public.admin_dashboard_touch (text, text, text),
    public.rest_admin_session_actor (uuid) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.auth_sessions_revoke_phone (text, text), public.admin_actor_phone (bigint, text),
    public.admin_session_authorised (text, text, text), public.rest_admin_session_actor (uuid) TO service_role;

GRANT EXECUTE ON FUNCTION public.portal_access (bigint, text), public.rest_admin_dashboard_mint (bigint, text, text, text),
    public.sys_admin_dashboard_mint (bigint, text, text), public.admin_dashboard_activate (text, text, text, text, text),
    public.admin_dashboard_touch (text, text, text) TO service_role;
