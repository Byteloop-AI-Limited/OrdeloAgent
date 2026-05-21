-- Canonical schema: auth_sessions
-- Generalized session table for all dashboard roles (admin, rider, ...).
-- Replaces dashboard_sessions.sql.
-- Run once on a fresh Supabase instance.
-- For existing instances with dashboard_sessions, run auth_sessions_migration.sql instead.

CREATE TABLE IF NOT EXISTS auth_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Role discriminator
  role              TEXT NOT NULL CHECK (role IN ('admin', 'rider')),

  -- Identity (set at creation, immutable)
  -- principal_id: admin_id for admin; rider_id (digits-only, no '+') for rider
  -- scope_ref:    rest_ref for admin; NULL for rider
  -- wa_number:    digits-only canonical form for all roles
  principal_id      TEXT NOT NULL,
  scope_ref         TEXT,
  wa_number         TEXT NOT NULL,

  -- Magic link token (sha256, never the raw token)
  -- NULL after activation so a leaked URL is useless even within TTL.
  token_hash        TEXT,

  -- Post-activation cookie token (sha256). NULL until activated.
  cookie_hash       TEXT,

  -- Lifecycle timestamps
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at        TIMESTAMPTZ NOT NULL,   -- 30 min from created_at; link TTL
  activated_at      TIMESTAMPTZ,            -- when cookie was first issued
  hard_expires_at   TIMESTAMPTZ,            -- activated_at + 4h; absolute cap
  last_seen_at      TIMESTAMPTZ,            -- updated on every authed request

  -- Binding (set at activation)
  bound_ip          INET,                   -- recorded but NOT enforced (mobile NAT)
  bound_ua_hash     TEXT,                   -- sha256(User-Agent), ENFORCED

  -- Revocation
  revoked           BOOLEAN NOT NULL DEFAULT FALSE,
  revoked_at        TIMESTAMPTZ,
  revoked_reason    TEXT,

  -- Invariants
  CONSTRAINT auth_sessions_scope_required_for_admin
    CHECK ((role = 'admin' AND scope_ref IS NOT NULL) OR role <> 'admin')
);

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_token_hash_idx
  ON auth_sessions(token_hash)
  WHERE token_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS auth_sessions_cookie_hash_idx
  ON auth_sessions(cookie_hash)
  WHERE cookie_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS auth_sessions_wa_number_idx
  ON auth_sessions(wa_number, created_at DESC);

CREATE INDEX IF NOT EXISTS auth_sessions_scope_ref_idx
  ON auth_sessions(scope_ref, created_at DESC)
  WHERE scope_ref IS NOT NULL;

-- Composite index for efficient lookup by role + principal (e.g. revoke all sessions for a rider)
CREATE INDEX IF NOT EXISTS auth_sessions_role_principal_idx
  ON auth_sessions(role, principal_id, created_at DESC);
