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
-- REQUIRES      core/rider_master.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   OrdeloAgent issues a WhatsApp magic link, or for restaurant admins also a Telegram /manage one
--                 (watomation/routers/rest_admin_auth_session.py, ordelo/rider_dashboard.py, sys_admin_auth_session.py): a row with token_hash and a 30-minute expires_at. Opening the link activates it: token_hash
--                 is cleared, cookie_hash set, hard_expires_at = activated_at + 4 h. restaurant-frontend's dashboards send the cookie on
--                 every request; last_seen_at is updated. Revoking a person's sessions = revoked_at on their rows.
-- LIFECYCLE     created (link sent) -> activated (cookie issued) -> expired (expires_at / hard_expires_at) or revoked.
-- CALLED BY     auth_sessions:
--                 python    watomation/routers/rest_admin_auth_session.py: mint_dashboard_session_for() (via mint_dashboard_session()
--                             for WhatsApp /login; directly from channels/telegram/rest_admin/manage.py for Telegram /manage)
--                 python    ordelo/rider_dashboard.py: issue_link()
--                 python    watomation/routers/sys_admin_auth_session.py: create_sys_admin_dashboard_session()
--               Rider RPCs: ordelo/rider_dashboard.py issue_link(); restaurant-frontend/lib/rider-session.ts.
-- PYTHON MODEL  ordelo/rider_dashboard.py DashboardLink
-- SECURITY      Table and rider RPCs are service-role only; RLS enabled. Apply reviewed cutover before code deployment.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.auth_sessions IS 'One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.';
