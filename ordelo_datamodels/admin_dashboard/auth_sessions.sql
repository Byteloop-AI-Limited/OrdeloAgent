-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/auth_sessions.sql
-- Magic-link login sessions for every dashboard role (restaurant admin, rider, sys-admin).
-- =============================================================================================
-- LIVE CHECK    Table columns verified read-only 2026-10-26. Rider RPCs and restricted grants below are proposed, not applied.
-- OBJECTS       table  auth_sessions
--                   One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.
--               fn     rider_dashboard_mint(p_tuid bigint, p_token_hash text) -> jsonb
--                   Atomically authorize the linked Telegram rider and mint a 30-minute credential.
--               fn     rider_dashboard_activate(p_token_hash text, p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Consume one rider token after explicit browser POST.
--               fn     rider_dashboard_session(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Read a complete valid rider session and its verified current linkage.
--               fn     rider_dashboard_touch(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Validate and execute the idle heartbeat without extending the absolute expiry.
--               fn     auth_sessions_revoke_phone(p_phone text, p_reason text) -> integer
--                   Revoke every rest_admin / sys_admin session and unused link of a phone (relink / unlink).
--               fn     admin_actor_phone(p_tuid bigint, p_phone text) -> text
--                   The verified phone of a Telegram or WhatsApp actor; locks its admin record.
--               fn     admin_session_authorised(p_role text, p_principal text, p_scope text) -> boolean
--                   The one authority test: roster membership (rest_admin) or overwatch (sys_admin).
--               fn     portal_access(p_tuid bigint, p_phone text) -> jsonb
--                   What a verified actor may open: its restaurants and whether it is sys-admin.
--               fn     rest_admin_dashboard_mint(p_tuid bigint, p_phone text, p_rest_ref text, p_token_hash text) -> jsonb
--                   Mint a 30-minute restaurant-dashboard link after re-checking membership.
--               fn     sys_admin_dashboard_mint(p_tuid bigint, p_phone text, p_token_hash text) -> jsonb
--                   Mint a 30-minute sys-admin link after re-checking overwatch.
--               fn     admin_dashboard_activate(p_role text, p_token_hash text, p_cookie_hash text, p_ua_hash text, p_ip text) -> jsonb
--                   Consume one rest_admin / sys_admin link after explicit browser POST.
--               fn     admin_dashboard_touch(p_role text, p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Validate a rest_admin / sys_admin cookie, re-check authority, execute the heartbeat.
--               fn     rest_admin_session_actor(p_session_id uuid, OUT phone text, OUT rest_ref text) -> record
--                   Phone and restaurant of a live, authorised rest_admin session, else RAISE not_authorised.
-- REQUIRES      core/rider_master.sql
--               restaurant_admin/admin_roster.sql (admin_roster, restaurant_admin, admin_phone_digits, is_overwatch)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   OrdeloAgent issues portal links (ordelo/dashboard_links.py, for Telegram /manage, /sysadmin, /portal, /my_jobs and
--                 WhatsApp /login, /sysadmin) through the mint RPCs below: a row with token_hash and a 30-minute expires_at. Opening
--                 the link shows a page that POSTs to activate it (restaurant-frontend lib/dashboard-activation.ts): token_hash
--                 is cleared, cookie_hash set, hard_expires_at = activated_at + 4 h. restaurant-frontend's dashboards send the cookie on
--                 every request; last_seen_at is updated. Revoking a person's sessions = revoked_at on their rows.
-- LIFECYCLE     created (link sent) -> activated (cookie issued) -> expired (expires_at / hard_expires_at) or revoked.
-- CALLED BY     auth_sessions:
--                 sql       every mint / activate / touch RPC below (no Python code inserts rows directly)
--                 python    watomation/routers/sys_admin_auth_session.py: require_sys_admin() (reads the payout proxy credential)
--                 frontend  restaurant-frontend lib/rest-admin-session.ts, lib/sys-admin-session.ts, lib/rider-session.ts (logout)
--               Rider RPCs: ordelo/dashboard_links.py issue("rider"); restaurant-frontend/lib/rider-session.ts.
--               portal_access, rest_admin_dashboard_mint, sys_admin_dashboard_mint:
--                 python    ordelo/dashboard_links.py: access(), issue()
--               admin_dashboard_activate, admin_dashboard_touch:
--                 frontend  restaurant-frontend/lib/rest-admin-session.ts, lib/sys-admin-session.ts (activateToken,
--                           validateCookieAndTouch)
--               auth_sessions_revoke_phone:
--                 sql       t_admin_link() (relinked), admin_unlink_telegram() (restaurant_admin/admin_roster.sql)
--               rest_admin_session_actor:
--                 sql       every rest_admin_* settings RPC (restaurant_admin/restaurant_settings.sql and siblings)
-- PYTHON MODEL  ordelo/dashboard_links.py (Actor, PortalAccess, PortalLink, Issued)
-- SECURITY      Table and every RPC are service-role only; RLS enabled. Helpers are granted to service_role because
--               nested SECURITY INVOKER calls run as the caller.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
--               tests/sql/test_admin_dashboard_sql.py
-- GOTCHAS       Only hashes are stored (sha256), never raw tokens.
--               Live grants were open on 2026-10-26; do not deploy without the reviewed access cutover.
-- SEE ALSO      test_support/test_magic_link.sql
--               _archive/dashboard_sessions.sql (the table this replaced; not live)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table auth_sessions
--   One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.auth_sessions (
    id uuid NOT NULL DEFAULT gen_random_uuid (),
    -- Role discriminator
    role text NOT NULL,
    -- Identity (set at creation, immutable)
    -- principal_id: rest_admin_id for rest_admin; rider_id (digits-only, no '+') for rider; sys_admin id for sys_admin
    -- scope_ref:    rest_ref for rest_admin; NULL for rider/sys_admin
    -- wa_number:    digits-only canonical form for all roles
    principal_id text NOT NULL,
    scope_ref text,
    wa_number text NOT NULL,
    -- Magic link token (sha256, never the raw token)
    -- NULL after activation so a leaked URL is useless even within TTL.
    token_hash text,
    -- Post-activation cookie token (sha256). NULL until activated.
    cookie_hash text,
    -- Lifecycle timestamps
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    expires_at timestamp with time zone NOT NULL, -- 30 min from created_at; link TTL
    activated_at timestamp with time zone, -- when cookie was first issued
    hard_expires_at timestamp with time zone, -- activated_at + 4h; absolute cap
    last_seen_at timestamp with time zone, -- updated on every authed request
    -- Binding (set at activation)
    bound_ip inet, -- recorded but NOT enforced (mobile NAT)
    bound_ua_hash text, -- sha256(User-Agent), ENFORCED
    -- Revocation
    revoked boolean NOT NULL DEFAULT FALSE,
    revoked_at timestamp with time zone,
    revoked_reason text,
    CONSTRAINT auth_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_sessions_role_check CHECK ((ROLE = ANY (ARRAY['rest_admin'::text, 'rider'::text, 'sys_admin'::text]))),
    CONSTRAINT auth_sessions_scope_required_for_rest_admin CHECK ((((ROLE = 'rest_admin'::text) AND (scope_ref IS NOT NULL)) OR (ROLE <> 'rest_admin'::text)))
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_cookie_hash_idx ON public.auth_sessions USING btree (cookie_hash)
WHERE (cookie_hash IS NOT NULL);

-- Composite index for efficient lookup by role + principal (e.g. revoke all sessions for a rider)
CREATE INDEX IF NOT EXISTS auth_sessions_role_principal_idx ON public.auth_sessions USING btree (ROLE, principal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS auth_sessions_scope_ref_idx ON public.auth_sessions USING btree (scope_ref, created_at DESC)
WHERE (scope_ref IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_token_hash_idx ON public.auth_sessions USING btree (token_hash)
WHERE (token_hash IS NOT NULL);

CREATE INDEX IF NOT EXISTS auth_sessions_wa_number_idx ON public.auth_sessions USING btree (wa_number, created_at DESC);

ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.auth_sessions FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.auth_sessions TO service_role;

-- rider_dashboard_mint: service-only actor authorization and session insert under the rider row lock.
-- Arguments are Telegram sender and SHA-256 token; returns result ok | not_linked.
-- Inactive/paused riders retain financial reads. Neither phone nor shift state authorizes issuance.
CREATE OR REPLACE FUNCTION public.rider_dashboard_mint (p_tuid bigint, p_token_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    r rider_master%ROWTYPE;
    n timestamptz;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' THEN
        RAISE EXCEPTION 'invalid token hash'
            USING ERRCODE = '22023';
        END IF;
        SELECT
            * INTO r
        FROM
            rider_master
        WHERE
            tuid = p_tuid
        FOR UPDATE;
        IF NOT FOUND OR r.phone_verified IS DISTINCT FROM TRUE OR r.t_linked_at IS NULL THEN
            RETURN jsonb_build_object('result', 'not_linked');
        END IF;
        n := clock_timestamp();
        INSERT INTO auth_sessions (role, principal_id, wa_number, token_hash, created_at, expires_at)
            VALUES ('rider', r.rider_id, r.rider_id, p_token_hash, n, n + interval '30 minutes');
        RETURN jsonb_build_object('result', 'ok');
END;
$$;

-- rider_dashboard_activate: lock rider before session; consume only an unexpired, unrevoked rider token.
-- Arguments are SHA-256 hashes. Returns result ok | invalid, with session_id on success.
-- Caller must use an explicit same-origin POST; raw tokens/cookies never enter the database.
CREATE OR REPLACE FUNCTION public.rider_dashboard_activate (p_token_hash text, p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    s auth_sessions%ROWTYPE;
    r rider_master%ROWTYPE;
    n timestamptz;
    sid uuid;
BEGIN
    IF p_token_hash IS NULL OR p_cookie_hash IS NULL OR p_ua_hash IS NULL OR p_token_hash !~ '^[a-f0-9]{64}$' OR p_cookie_hash !~ '^[a-f0-9]{64}$' OR p_ua_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    SELECT
        * INTO s
    FROM
        auth_sessions
    WHERE
        token_hash = p_token_hash
        AND ROLE = 'rider';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    SELECT
        * INTO r
    FROM
        rider_master
    WHERE
        rider_id = s.principal_id
    FOR UPDATE;
    IF NOT FOUND OR r.tuid IS NULL OR r.phone_verified IS DISTINCT FROM TRUE OR r.t_linked_at IS NULL OR s.created_at < r.t_linked_at THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    n := clock_timestamp();
    UPDATE
        auth_sessions
    SET
        token_hash = NULL,
        cookie_hash = p_cookie_hash,
        activated_at = n,
        last_seen_at = n,
        hard_expires_at = n + interval '4 hours',
        bound_ua_hash = p_ua_hash
    WHERE
        id = s.id
        AND ROLE = 'rider'
        AND token_hash = p_token_hash
        AND NOT revoked
        AND activated_at IS NULL
        AND expires_at > n
    RETURNING
        id INTO sid;
    IF sid IS NULL THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'session_id', sid);
END;
$$;

-- rider_dashboard_session: pure authorization read, used by the jobs statement and heartbeat.
-- Arguments are cookie/UA hashes. Returns result ok | invalid, plus internal session/principal on success.
-- Requires complete activation, idle and hard expiry, verified link and generation; status is deliberately irrelevant.
CREATE OR REPLACE FUNCTION public.rider_dashboard_session (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    SELECT
        coalesce((
            SELECT
                jsonb_build_object('result', 'ok', 'session_id', s.id, 'rider_id', s.principal_id)
            FROM auth_sessions s
            JOIN rider_master r ON r.rider_id = s.principal_id
            WHERE
                s.cookie_hash = p_cookie_hash
                AND s.bound_ua_hash = p_ua_hash
                AND s.role = 'rider'
                AND NOT s.revoked
                AND s.activated_at IS NOT NULL
                AND s.token_hash IS NULL
                AND s.hard_expires_at > statement_timestamp()
            AND s.last_seen_at > statement_timestamp() - interval '60 minutes'
        AND r.tuid IS NOT NULL
        AND r.phone_verified
        AND r.t_linked_at IS NOT NULL
        AND s.created_at >= r.t_linked_at), jsonb_build_object('result', 'invalid'));
$$;

-- rider_dashboard_touch: execute (not fire-and-forget) the session idle heartbeat.
-- Returns result ok | invalid; never changes revoked/absolute expiry or resurrects a malformed session.
CREATE OR REPLACE FUNCTION public.rider_dashboard_touch (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    out jsonb;
BEGIN
    out := rider_dashboard_session (p_cookie_hash, p_ua_hash);
    IF out ->> 'result' <> 'ok' THEN
        RETURN out;
    END IF;
    UPDATE
        auth_sessions
    SET
        last_seen_at = clock_timestamp()
    WHERE
        id = (out ->> 'session_id')::uuid
        AND NOT revoked
        AND hard_expires_at > clock_timestamp()
        AND last_seen_at > clock_timestamp() - interval '60 minutes';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    RETURN out;
END;
$$;

REVOKE ALL ON FUNCTION public.rider_dashboard_mint (bigint, text), public.rider_dashboard_activate (text, text, text), public.rider_dashboard_session (text, text), public.rider_dashboard_touch (text, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_dashboard_mint (bigint, text), public.rider_dashboard_activate (text, text, text), public.rider_dashboard_session (text, text), public.rider_dashboard_touch (text, text) TO service_role;

COMMENT ON FUNCTION public.rider_dashboard_mint (bigint, text) IS 'Mint a rider login for the verified Telegram actor under the rider lock.';

COMMENT ON FUNCTION public.rider_dashboard_activate (text, text, text) IS 'Atomically consume one unexpired rider login token after explicit POST.';

COMMENT ON FUNCTION public.rider_dashboard_session (text, text) IS 'Authorize a complete rider session against its current verified link and expiry.';

COMMENT ON FUNCTION public.rider_dashboard_touch (text, text) IS 'Authorize and execute the rider session heartbeat without extending its hard expiry.';

-- =============================================================================================
-- Admin dashboards (rest_admin, sys_admin): portal access, issuance and sessions.
-- plans/telegram-portal-links-and-dashboard-plan.md M2/M5/M6. Every function: service-role only.
-- Actor = exactly one of p_tuid (Telegram from_user.id, linked by a verified contact share: restaurant_admin.tuid) or
-- p_phone (WhatsApp wa_id, verified by Meta). Authority is re-derived on every call: restaurant rights from admin_roster
-- (restaurant_master.admins), system rights from is_overwatch(). Nothing here trusts a caller-asserted rest_ref alone.
-- =============================================================================================

-- auth_sessions_revoke_phone: revoke every unrevoked rest_admin / sys_admin session and unused link of one phone.
-- Called by t_admin_link() (relinked) and admin_unlink_telegram() in their transaction. Returns the number revoked.
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

-- admin_actor_phone: the verified phone of the actor, or NULL. Locks the admin record when it exists (FOR UPDATE)
-- so issuance serialises with t_admin_link() relinks of the same phone.
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

-- admin_session_authorised: does this principal still hold this role (and scope)? The one authority test for
-- issuance, activation, every protected request and every settings write.
-- plpgsql (not sql) so this file can be applied before admin_roster.sql exists (bodies are bound at call time).
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

-- portal_access: what this actor may open. {result: ok | not_linked, phone, restaurants:[{rest_ref, rest_name}], sys_admin}.
-- ok with restaurants = [] and sys_admin = false means "verified, but nothing to open". Read-only (no lock).
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

-- rest_admin_dashboard_mint: one 30-minute single-use restaurant-dashboard link. {result: ok | not_linked | not_allowed}.
-- Membership of p_rest_ref is re-checked under the admin-record lock; the session stores the verified phone.
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

-- sys_admin_dashboard_mint: one 30-minute single-use sys-admin link. {result: ok | not_linked | not_allowed}.
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

-- admin_dashboard_activate: consume one rest_admin / sys_admin link after the browser's explicit POST.
-- {result: ok, session_id} | {result: invalid, reason: not_found | revoked | already_used | expired | not_authorised}.
-- The row lock makes concurrent taps safe: the loser sees the token already cleared (not_found).
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

-- admin_dashboard_touch: validate a rest_admin / sys_admin browser credential and execute the idle heartbeat.
-- {result: ok, session_id, principal_id, scope_ref, wa_number}
-- | {result: invalid, reason: no_session | revoked | ua_mismatch | hard_cap | idle | not_authorised}.
-- not_authorised (removed from the list / overwatch since sign-in) also revokes the session.
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

-- rest_admin_session_actor: the phone and restaurant of a live, still-authorised rest_admin session, else RAISE
-- 'not_authorised' (SQLSTATE 28000). Internal: called first by every restaurant-dashboard settings RPC, which takes the
-- session id stamped by the frontend middleware instead of any rest_ref or phone from the browser.
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

-- Helpers are SECURITY INVOKER, so the service role needs EXECUTE on them too (nested calls run as the caller).
GRANT EXECUTE ON FUNCTION public.auth_sessions_revoke_phone (text, text), public.admin_actor_phone (bigint, text),
    public.admin_session_authorised (text, text, text), public.rest_admin_session_actor (uuid) TO service_role;

GRANT EXECUTE ON FUNCTION public.portal_access (bigint, text), public.rest_admin_dashboard_mint (bigint, text, text, text),
    public.sys_admin_dashboard_mint (bigint, text, text), public.admin_dashboard_activate (text, text, text, text, text),
    public.admin_dashboard_touch (text, text, text) TO service_role;

COMMENT ON FUNCTION public.portal_access (bigint, text) IS 'What a verified actor may open: its restaurants and whether it is sys-admin (overwatch).';

COMMENT ON FUNCTION public.rest_admin_dashboard_mint (bigint, text, text, text) IS 'Mint a 30-minute restaurant-dashboard link after re-checking roster membership under the admin lock.';

COMMENT ON FUNCTION public.sys_admin_dashboard_mint (bigint, text, text) IS 'Mint a 30-minute sys-admin link after re-checking overwatch membership.';

COMMENT ON FUNCTION public.admin_dashboard_activate (text, text, text, text, text) IS 'Consume one rest_admin / sys_admin link after explicit POST; re-checks authority.';

COMMENT ON FUNCTION public.admin_dashboard_touch (text, text, text) IS 'Validate a rest_admin / sys_admin cookie, re-check authority and execute the idle heartbeat.';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.auth_sessions IS 'One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.';
