-- Migration: dashboard_sessions
-- PRD: PRD-admin-magic-link.md §4.1
-- Run once in Supabase SQL editor.

CREATE TABLE IF NOT EXISTS dashboard_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identity (set at creation, immutable)
  admin_id          TEXT      NOT NULL,
  rest_ref          TEXT      NOT NULL,
  wa_number         TEXT      NOT NULL,

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
  revoked_reason    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS dashboard_sessions_token_hash_idx
  ON dashboard_sessions(token_hash)
  WHERE token_hash IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS dashboard_sessions_cookie_hash_idx
  ON dashboard_sessions(cookie_hash)
  WHERE cookie_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS dashboard_sessions_wa_number_idx
  ON dashboard_sessions(wa_number, created_at DESC);

CREATE INDEX IF NOT EXISTS dashboard_sessions_rest_ref_idx
  ON dashboard_sessions(rest_ref, created_at DESC);
