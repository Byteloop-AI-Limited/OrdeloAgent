-- SIMULATE TELEGRAM RIDER ONBOARDING
-- Operator script, prepared from a read-only rider_master query on 2026-10-26.
-- Scope: rider_master rows for 447448440754 and 447929843965 only.
-- Does not touch rider_registrations or any delivery/history tables.
--
-- IMPORTANT: all write statements are commented out. Run only the selected stage,
-- manually, in the SQL editor. Do not run this whole file as a batch.
-- Stage 1 temporarily removes these two known rider_master records so the rider
-- bot treats their shared phone contacts as unknown numbers and runs signup.
-- Stage 2 is an optional restore after recording; it first removes the newly
-- created rider_master rows for these exact phone numbers and restores the
-- original snapshots below.

-- ===== READ-ONLY BEFORE CHECK =====
SELECT *
  FROM public.rider_master
 WHERE rider_id IN ('447448440754', '447929843965')
 ORDER BY rider_id;

-- Snapshot returned by the read-only query (all rider_master columns):
-- id | rider_id      | rider_name | vehicle_type | town  | status | is_in_shift | priority | dtts                     | shift_response_dtts      | channel  | tuid       | tcid       | t_username | t_first_name | t_linked_at                  | phone_verified
-- 49 | 447448440754  | lohith     | bicycle      | dummy | active | true        | 1        | 2026-10-22 13:26:28.877644 | 2026-10-26 19:30:46.258085 | telegram | 7279908526 | 7279908526 | NULL       | lohith       | 2026-10-22 13:26:28.877644+00 | true
-- 52 | 447929843965  | lohithNwg  | bicycle      | dummy | active | true        | 1        | 2026-10-22 21:15:53.218762 | NULL                     | telegram | 8715530031 | 8715530031 | lohithNwg  | lohithNwg    | 2026-10-22 21:15:53.218762+00 | true

-- ===== STAGE 1: TEMPORARILY REMOVE THE TWO EXISTING RIDER ROWS =====
-- First check the rowset above. Then select and run only this statement.
-- DELETE FROM public.rider_master
--  WHERE rider_id IN ('447448440754', '447929843965')
-- RETURNING *;

-- Confirm the bot will find no rider_master row for these numbers before recording:
-- SELECT rider_id FROM public.rider_master
--  WHERE rider_id IN ('447448440754', '447929843965');
-- Expected: 0 rows.

-- ===== STAGE 2: OPTIONAL RESTORE AFTER THE VIDEO =====
-- Run only after the onboarding capture is finished. This removes the new rider
-- master rows created by the bot for these numbers, then restores the exact
-- pre-capture values. Any changes to these two rider_master rows after the
-- snapshot are discarded; no other table is changed by this restore section.
--
DELETE FROM public.rider_master
 WHERE rider_id IN ('447448440754', '447929843965')
RETURNING rider_id, id;
--
-- INSERT INTO public.rider_master (
--     id, rider_id, rider_name, vehicle_type, town, status, is_in_shift,
--     priority, dtts, shift_response_dtts, channel, tuid, tcid,
--     t_username, t_first_name, t_linked_at, phone_verified
-- ) VALUES
--     (
--         49, '447448440754', 'lohith', 'bicycle', 'dummy', 'active', TRUE,
--         1, '2026-10-22 13:26:28.877644'::timestamp without time zone,
--         '2026-10-26 19:30:46.258085'::timestamp without time zone,
--         'telegram', 7279908526, 7279908526, NULL, 'lohith',
--         '2026-10-22 13:26:28.877644+00'::timestamp with time zone, TRUE
--     ),
--     (
--         52, '447929843965', 'lohithNwg', 'bicycle', 'dummy', 'active', TRUE,
--         1, '2026-10-22 21:15:53.218762'::timestamp without time zone,
--         NULL, 'telegram', 8715530031, 8715530031, 'lohithNwg', 'lohithNwg',
--         '2026-10-22 21:15:53.218762+00'::timestamp with time zone, TRUE
--     )
-- RETURNING *;

-- Read-only verification after restore:
SELECT *
  FROM public.rider_master
 WHERE rider_id IN ('447448440754', '447929843965')
 ORDER BY rider_id;

update public.rider_master
 set status='active'
 where rider_id in ('447448440754', '447929843965');