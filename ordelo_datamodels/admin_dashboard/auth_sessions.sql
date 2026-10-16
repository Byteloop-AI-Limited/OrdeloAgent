-- Canonical schema: auth_sessions
-- Generalized session table for all dashboard roles (rest_admin, rider, sys_admin, ...).
-- Replaces _archive/dashboard_sessions.sql.
-- Run once on a fresh Supabase instance.
-- For existing instances with dashboard_sessions, run auth_sessions_migration.sql instead.
CREATE TABLE IF NOT EXISTS public.auth_sessions (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
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
    revoked boolean NOT NULL DEFAULT false,
    revoked_at timestamp with time zone,
    revoked_reason text,
    CONSTRAINT auth_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT auth_sessions_role_check CHECK ((role = ANY (ARRAY['rest_admin'::text, 'rider'::text, 'sys_admin'::text]))),
    CONSTRAINT auth_sessions_scope_required_for_rest_admin CHECK ((((role = 'rest_admin'::text) AND (scope_ref IS NOT NULL)) OR (role <> 'rest_admin'::text)))
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_cookie_hash_idx ON public.auth_sessions USING btree (cookie_hash) WHERE (cookie_hash IS NOT NULL);

-- Composite index for efficient lookup by role + principal (e.g. revoke all sessions for a rider)
CREATE INDEX IF NOT EXISTS auth_sessions_role_principal_idx ON public.auth_sessions USING btree (role, principal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS auth_sessions_scope_ref_idx ON public.auth_sessions USING btree (scope_ref, created_at DESC) WHERE (scope_ref IS NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_token_hash_idx ON public.auth_sessions USING btree (token_hash) WHERE (token_hash IS NOT NULL);

CREATE INDEX IF NOT EXISTS auth_sessions_wa_number_idx ON public.auth_sessions USING btree (wa_number, created_at DESC);
