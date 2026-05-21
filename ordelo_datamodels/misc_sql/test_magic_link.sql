-- Test fixtures for the magic-link auth flow (admin + rider).
-- Schema: auth_sessions (generalized from dashboard_sessions — see auth_sessions_migration.sql)
-- PRDs: PRD-admin-magic-link.md, PRD-rider-magic-link.md
--
-- Supabase has pgcrypto enabled by default, so we compute SHA-256 inline.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Reset between test runs
-- ---------------------------------------------------------------------------
DELETE FROM auth_sessions
WHERE principal_id IN (
  'adm_test_001', 'adm_test_002', 'adm_test_003',
  '447448440754', '447448440755', '447448440756',
  '447900000001', '447900000002', '447900000003'
);


-- ===========================================================================
-- REST_ADMIN fixtures
-- ===========================================================================

-- 1. Rest-admin happy path: valid, unactivated link
--    URL: http://localhost:3000/rest-admin/activate/elas2
--    Expected: 302 -> /rest-admin, __Host-radash cookie set, top bar shows "ELAS"
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'rest_admin',
  'adm_test_001',
  'ELAS',
  '447919202938',
  encode(digest('elas2', 'sha256'), 'hex'),
  now() + interval '30 minutes'
);

-- 2. Rest-admin expired link -> /rest-admin/expired?reason=expired
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'rest_admin',
  'adm_test_002',
  'elas',
  '447919202938',
  encode(digest('admin-expired-token', 'sha256'), 'hex'),
  now() - interval '1 minute'
);
-- URL: http://localhost:3000/rest-admin/activate/admin-expired-token

-- 3. Rest-admin revoked before activation -> /rest-admin/expired?reason=revoked
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at,
  revoked, revoked_at, revoked_reason
) VALUES (
  'rest_admin',
  'adm_test_003',
  'elas',
  '447919202938',
  encode(digest('admin-revoked-token', 'sha256'), 'hex'),
  now() + interval '30 minutes',
  true, now(), 'test'
);
-- URL: http://localhost:3000/rest-admin/activate/admin-revoked-token


-- ===========================================================================
-- RIDER fixtures
-- ===========================================================================

-- 4. Rider happy path: valid, unactivated link
--    URL: http://localhost:3000/rider/activate/test-rider-token
--    Expected: 302 -> /rider/jobs, __Host-rdash cookie set
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'rider',
  '447448440754',
  NULL,
  '447448440754',
  encode(digest('test-rider-token', 'sha256'), 'hex'),
  now() + interval '30 minutes'
);

-- 5. Rider expired link -> /rider/expired?reason=expired
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'rider',
  '447448440755',
  NULL,
  '447448440755',
  encode(digest('rider-expired-token', 'sha256'), 'hex'),
  now() - interval '1 minute'
);
-- URL: http://localhost:3000/rider/activate/rider-expired-token

-- 6. Rider revoked before activation -> /rider/expired?reason=revoked
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at,
  revoked, revoked_at, revoked_reason
) VALUES (
  'rider',
  '447448440756',
  NULL,
  '447448440756',
  encode(digest('rider-revoked-token', 'sha256'), 'hex'),
  now() + interval '30 minutes',
  true, now(), 'test'
);
-- URL: http://localhost:3000/rider/activate/rider-revoked-token


-- ===========================================================================
-- SYS_ADMIN fixtures
-- ===========================================================================
-- Unlike rest_admin / rider, sys_admin has NO tenant scoping. Every logged-in
-- sys_admin sees all data (riders-inshift, rider payouts, restaurant_master).
-- scope_ref is therefore always NULL. principal_id mirrors the rider pattern:
-- digits-only wa_number, no leading '+'.

-- 7. Sys-admin happy path: valid, unactivated link
--    URL: http://localhost:3000/sys-admin/activate/sa-token-happy
--    Expected: 302 -> /sys-admin (redirects on to /sys-admin/riders-inshift),
--              __Host-sdash cookie set, top bar shows "sys-admin · riders".
delete from auth_sessions where role = 'sys_admin';
EXPLAIN ANALYZE
SELECT *
FROM auth_sessions
WHERE token_hash = encode(digest('sa-token-happy', 'sha256'), 'hex')
LIMIT 1;
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'sys_admin',
  '447448440754',
  NULL,
  '447448440754',
  encode(digest('sa-token-happy', 'sha256'), 'hex'),
  now() + interval '30 minutes'
);

-- 8. Sys-admin expired link -> /sys-admin/expired?reason=expired
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at
) VALUES (
  'sys_admin',
  '447900000002',
  NULL,
  '447900000002',
  encode(digest('sa-expired-token', 'sha256'), 'hex'),
  now() - interval '1 minute'
);
-- URL: http://localhost:3000/sys-admin/activate/sa-expired-token

-- 9. Sys-admin revoked before activation -> /sys-admin/expired?reason=revoked
INSERT INTO auth_sessions (
  role, principal_id, scope_ref, wa_number, token_hash, expires_at,
  revoked, revoked_at, revoked_reason
) VALUES (
  'sys_admin',
  '447900000003',
  NULL,
  '447900000003',
  encode(digest('sa-revoked-token', 'sha256'), 'hex'),
  now() + interval '30 minutes',
  true, now(), 'test'
);
-- URL: http://localhost:3000/sys-admin/activate/sa-revoked-token


-- ===========================================================================
-- Inspect rows
-- ===========================================================================
SELECT
  id,
  role,
  principal_id,
  scope_ref,
  wa_number,
  token_hash IS NULL         AS token_consumed,
  cookie_hash IS NOT NULL    AS cookie_issued,
  activated_at,
  last_seen_at,
  hard_expires_at,
  bound_ua_hash IS NOT NULL  AS ua_bound,
  bound_ip,
  revoked,
  expires_at
FROM auth_sessions
WHERE principal_id IN (
  'adm_test_001', 'adm_test_002', 'adm_test_003',
  '447448440754', '447448440755', '447448440756',
  '447900000001', '447900000002', '447900000003'
)
ORDER BY role, created_at DESC;


-- ===========================================================================
-- Seed delivery_dispatch rows for rider 447448440754 (smoke test)
-- ===========================================================================
-- Run after activating the rider token. Reload /rider/jobs.
-- Summary should show: Jobs: 3 · Paid: £6.50 · Unpaid: £7.20

/*
INSERT INTO delivery_dispatch
  (order_number, rider_id, rider_payout, vehicle_type, distance, status, dt, dtts, paid_status, paid_dtts)
VALUES
  ('ORD-R100', '447448440754', 6.50, 'bicycle', 1.2, 'completed', current_date, now() - interval '1 day',   'paid',   now() - interval '22 hours'),
  ('ORD-R101', '447448440754', 7.20, 'bicycle', 1.8, 'completed', current_date, now() - interval '2 hours', 'unpaid', NULL),
  ('ORD-R102', '447448440754', 0.00, 'bicycle', 0.0, 'declined',  current_date, now() - interval '3 hours', 'unpaid', NULL);
*/


-- ===========================================================================
-- Manual acceptance scenarios
-- ===========================================================================
-- (a) Re-open activated link
--       Visit the same activate URL a second time
--       -> expired?reason=not_found  (token_hash was NULLed on first use)
--
-- (b) UA mismatch
--       Activate in Browser A, copy __Host-radash/__Host-rdash to Browser B
--       -> expired?reason=ua_mismatch
--
-- (c) Idle timeout (rest_admin)
--       UPDATE auth_sessions
--          SET last_seen_at = now() - interval '61 minutes'
--        WHERE role = 'rest_admin' AND principal_id = 'adm_test_001';
--       Hit /rest-admin -> expired?reason=idle
--
-- (c) Idle timeout (rider)
--       UPDATE auth_sessions
--          SET last_seen_at = now() - interval '61 minutes'
--        WHERE role = 'rider' AND principal_id = '447448440754';
--       Hit /rider -> expired?reason=idle
--
-- (d) Hard cap
--       UPDATE auth_sessions
--          SET hard_expires_at = now() - interval '1 minute'
--        WHERE principal_id = 'adm_test_001';   -- or rider
--       -> expired?reason=hard_cap
--
-- (e) Logout
--       /rest-admin/more or /rider/more -> "Log out"
--       -> expired?reason=user_logout
--       Subsequent visit -> expired?reason=no_cookie
--
-- (f) Cross-role rejection
--       Copy __Host-rdash value, set it as __Host-radash in DevTools, visit /rest-admin
--       -> expired?reason=no_session  (role predicate blocks cross-role resolution)
--       Reverse: admin cookie against /rider -> same result


-- ===========================================================================
-- Sys-admin acceptance scenarios
-- ===========================================================================
-- (g) Happy path
--       Visit /sys-admin/activate/sa-token-happy
--       -> 302 /sys-admin -> /sys-admin/riders-inshift, __Host-sdash set
--       Bottom nav cycles between Riders | Payouts | Restaurants.
--
-- (h) Re-open activated sys-admin link
--       Visit /sys-admin/activate/sa-token-happy again
--       -> /sys-admin/expired?reason=not_found  (token_hash was NULLed on first use)
--
-- (i) Idle timeout (sys_admin)
--       UPDATE auth_sessions
--          SET last_seen_at = now() - interval '61 minutes'
--        WHERE role = 'sys_admin' AND principal_id = '447900000001';
--       Hit /sys-admin -> expired?reason=idle
--
-- (j) Hard cap (sys_admin)
--       UPDATE auth_sessions
--          SET hard_expires_at = now() - interval '1 minute'
--        WHERE principal_id = '447900000001';
--       -> expired?reason=hard_cap
--
-- (k) Logout (sys_admin)
--       Click "Log out" in the sys-admin top bar
--       -> expired?reason=user_logout
--       Subsequent visit -> expired?reason=no_cookie
--
-- (l) Cross-role rejection involving sys-admin
--       Copy __Host-sdash value, set it as __Host-radash in DevTools, visit /rest-admin
--       -> expired?reason=no_session  (TS-level role guard blocks resolution)
--       Reverse pairings (rdash -> sdash, radash -> sdash) behave identically.


-- ===========================================================================
-- Optional: seed a restaurant_master row for the sys-admin editor
-- ===========================================================================
-- Run after activating the sys-admin token. Visit /sys-admin/restaurants,
-- pick the row, edit admins / city / service_hours_json, click Save, then
-- re-run the SELECT below to confirm the PATCH persisted.

/*
INSERT INTO restaurant_master (
  rest_ref, rest_id, rest_name, house_number, street_name,
  city, postcode, lat, lon,
  admins, rest_stale_active_threads_minutes, service_hours_json
) VALUES (
  'TEST', 'TEST-0001', 'Sys-Admin Test Restaurant',
  '1', 'Test Street', 'Salisbury', 'SP1 1AA', 51.0688, -1.7945,
  ARRAY['447900000001'],
  10,
  '{
    "mon": [["16:00", "24:00"]],
    "tue": [["16:00", "24:00"]],
    "wed": [["16:00", "24:00"]],
    "thu": [["16:00", "24:00"]],
    "fri": [["16:00", "24:00"]],
    "sat": [["16:00", "25:00"]],
    "sun": [["16:00", "25:00"]]
  }'::jsonb
)
ON CONFLICT (rest_ref) DO NOTHING;

SELECT rest_ref, city, admins, rest_stale_active_threads_minutes, service_hours_json
FROM   restaurant_master
WHERE  rest_ref = 'TEST';
*/
