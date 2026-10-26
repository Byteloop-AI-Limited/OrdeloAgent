-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/auth_sessions.sql
-- Magic-link login sessions for every dashboard role (restaurant admin, rider, sys-admin).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  auth_sessions
--                   One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   OrdeloAgent issues a WhatsApp magic link, or for restaurant admins also a Telegram /manage one
--                 (watomation/routers/rest_admin_auth_session.py, rider_auth_session.py, sys_admin_auth_session.py): a row with token_hash and a 30-minute expires_at. Opening the link activates it: token_hash
--                 is cleared, cookie_hash set, hard_expires_at = activated_at + 4 h. restaurant-frontend's dashboards send the cookie on
--                 every request; last_seen_at is updated. Revoking a person's sessions = revoked_at on their rows.
-- LIFECYCLE     created (link sent) -> activated (cookie issued) -> expired (expires_at / hard_expires_at) or revoked.
-- CALLED BY     auth_sessions:
--                 python    watomation/routers/rest_admin_auth_session.py: mint_dashboard_session_for() (via mint_dashboard_session()
--                             for WhatsApp /login; directly from channels/telegram/rest_admin/manage.py for Telegram /manage)
--                 python    watomation/routers/rider_auth_session.py: create_rider_dashboard_session()
--                 python    watomation/routers/sys_admin_auth_session.py: create_sys_admin_dashboard_session()
-- PYTHON MODEL  none
-- SECURITY      auth_sessions: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       Only hashes are stored (sha256), never raw tokens.
--               RLS is off with default grants: anon can read session rows (hashes, phone numbers): part of the security review.
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.auth_sessions IS 'One login session: role, principal and scope, phone, token/cookie hashes, expiries, binding and revocation.';
