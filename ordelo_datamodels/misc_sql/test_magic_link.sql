-- Test fixtures for the admin magic-link flow.
-- PRD: PRD-admin-magic-link.md
--
-- Supabase has pgcrypto enabled by default, so we compute the SHA-256
-- inline -- no need to hash the token client-side.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- 1. Happy path: a valid, unactivated link
--    The raw token is what goes in the URL. Pick any string.
--    URL becomes: <host>/admin/activate/<token>
-- ---------------------------------------------------------------------------
delete from dashboard_sessions;
INSERT INTO dashboard_sessions (
  admin_id,
  rest_ref,
  wa_number,
  token_hash,
  expires_at
) VALUES (
  'adm_test_001',
  'ELAS',
  '447919202938',
  encode(digest('elas2', 'sha256'), 'hex'),
  now() + interval '30 minutes'
);
select * from dashboard_sessions;
-- Visit: http://localhost:3000/admin/activate/elas2
-- Expected: 302 -> /admin, __Host-ddash cookie set, top bar shows "ELAS".


-- ---------------------------------------------------------------------------
-- 2. Already-expired link  -> /admin/expired?reason=expired
-- ---------------------------------------------------------------------------
INSERT INTO dashboard_sessions (
  admin_id, rest_ref, wa_number, token_hash, expires_at
) VALUES (
  'adm_test_002', 'elas', '+919876543210',
  encode(digest('expired-token', 'sha256'), 'hex'),
  now() - interval '1 minute'
);

-- Visit: http://localhost:3000/admin/activate/expired-token


-- ---------------------------------------------------------------------------
-- 3. Revoked-before-activation  -> /admin/expired?reason=revoked
-- ---------------------------------------------------------------------------
INSERT INTO dashboard_sessions (
  admin_id, rest_ref, wa_number, token_hash, expires_at,
  revoked, revoked_at, revoked_reason
) VALUES (
  'adm_test_003', 'elas', '+919876543210',
  encode(digest('revoked-token', 'sha256'), 'hex'),
  now() + interval '30 minutes',
  true, now(), 'test'
);

-- Visit: http://localhost:3000/admin/activate/revoked-token


-- ---------------------------------------------------------------------------
-- Inspect rows after activation
-- ---------------------------------------------------------------------------
-- SELECT
--   id,
--   admin_id,
--   rest_ref,
--   token_hash IS NULL         AS token_consumed,
--   cookie_hash IS NOT NULL    AS cookie_issued,
--   activated_at,
--   last_seen_at,
--   hard_expires_at,
--   bound_ua_hash IS NOT NULL  AS ua_bound,
--   bound_ip,
--   revoked
-- FROM dashboard_sessions
-- ORDER BY created_at DESC
-- LIMIT 10;


-- ---------------------------------------------------------------------------
-- Cleanup between test runs
-- ---------------------------------------------------------------------------
-- DELETE FROM dashboard_sessions
-- WHERE admin_id IN ('adm_test_001', 'adm_test_002', 'adm_test_003');


-- ---------------------------------------------------------------------------
-- Additional acceptance scenarios (manual)
-- ---------------------------------------------------------------------------
-- (a) Re-visit token from fixture #1 after activation
--     -> /admin/expired?reason=not_found  (token_hash was cleared)
--
-- (b) UA-mismatch: activate in Browser A, copy the __Host-ddash cookie to
--     Browser B, visit /admin
--     -> /admin/expired?reason=ua_mismatch
--
-- (c) Idle timeout: after activation, manually backdate last_seen_at:
--       UPDATE dashboard_sessions
--          SET last_seen_at = now() - interval '61 minutes'
--        WHERE admin_id = 'adm_test_001';
--     Then hit /admin  -> /admin/expired?reason=idle
--
-- (d) Hard cap: backdate hard_expires_at into the past:
--       UPDATE dashboard_sessions
--          SET hard_expires_at = now() - interval '1 minute'
--        WHERE admin_id = 'adm_test_001';
--     Then hit /admin  -> /admin/expired?reason=hard_cap
--
-- (e) Logout: from /admin/more, click "Log out"
--     -> /admin/expired?reason=user_logout
--     Subsequent /admin visit (cookie cleared) -> /admin/expired?reason=no_cookie
