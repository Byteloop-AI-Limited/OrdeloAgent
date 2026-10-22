-- =============================================================================================
-- ordelo_datamodels/availability/rider_shift.sql
-- A rider starts or ends a shift (rider_master.is_in_shift), with the status gate and the on-a-job check in one place.
-- =============================================================================================
-- LIVE CHECK    NOT yet live (phase R5 of plans/telegram-rider-bot-plan.md). migrations/rider_telegram_r5_r6.sql step 3 applies it.
-- OBJECTS       fn     rider_set_shift(p_rider_id text, p_on boolean) -> jsonb
--                   Start (p_on) or end a rider's shift: only an 'active' rider can start, and nobody can end one during a job.
-- REQUIRES      core/rider_master.sql
--               dispatch/delivery_inflight.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (one function).
-- HOW IT FITS   is_in_shift is one of the dispatch gates (get_available_riders(): status = 'active' AND is_in_shift AND not paused).
--                 WhatsApp riders answer the daily shift question (dispatch/enquire_shift_availability.sql, 11:00 UTC): "Yes"
--                 -> rider_set_shift(rider, true); "No" -> rider_set_shift(rider, false) (watomation/on_callback_wa_handler.py).
--                 Telegram riders are on by default and step away with a pause instead (availability/pauses.sql, ADR 0013); /on
--                 on the rider bot calls rider_set_shift(rider, true) as well, so a Telegram rider whose flag was cleared (by an
--                 operator, or by the shift question before R5) is switched back on by the same gate.
--                 The status gate (D41): only status = 'active' (exact) may start a shift; a Telegram sign-up starts 'inactive'
--                 and stays out of dispatch until an operator activates it, whatever the rider taps.
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 p_on true:  on | not_active (+ status) | not_found
--                 p_on false: off | on_job (+ order_number) | not_found
--               on sets is_in_shift = true and shift_response_dtts = now(); off sets is_in_shift = false (shift_response_dtts kept,
--                 as the WhatsApp "No" always did).
-- CALLED BY     rider_set_shift:
--                 python    ordelo/rider_shift.py: set_shift()
-- PYTHON MODEL  ordelo/rider_shift.py (ShiftOutcome)
-- SECURITY      rider_set_shift(): REVOKE ALL FROM PUBLIC, anon, authenticated (service role only; client_ordelo_service).
-- TESTS         tests/sql/test_rider_shift_sql.py
--               tests/ordelo/test_rider_shift.py
-- GOTCHAS       on_job is checked against delivery_inflight (the rider's live job), the same check the WhatsApp "No" made.
--               A rider who is not active can still end a shift (harmless; they are not dispatched either way).
-- SEE ALSO      dispatch/enquire_shift_availability.sql
--               dispatch/job_create_dispatch.sql
--               availability/pauses.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function rider_set_shift(p_rider_id text, p_on boolean) -> jsonb
--   Start (p_on) or end a rider's shift: only an 'active' rider can start, and nobody can end one during a job.
--   Data: reads delivery_inflight; reads/writes rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_set_shift (p_rider_id text, p_on boolean)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status text;
    v_order text;
BEGIN
    SELECT
        status INTO v_status
    FROM
        rider_master
    WHERE
        rider_id = p_rider_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    IF p_on THEN
        IF v_status IS DISTINCT FROM 'active' THEN
            RETURN jsonb_build_object('result', 'not_active', 'status', v_status);
        END IF;
        UPDATE
            rider_master
        SET
            is_in_shift = TRUE,
            shift_response_dtts = now()
        WHERE
            rider_id = p_rider_id;
        RETURN jsonb_build_object('result', 'on');
    END IF;
    SELECT
        order_number INTO v_order
    FROM
        delivery_inflight
    WHERE
        rider_id = p_rider_id
    LIMIT 1;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'on_job', 'order_number', v_order);
    END IF;
    UPDATE
        rider_master
    SET
        is_in_shift = FALSE
    WHERE
        rider_id = p_rider_id;
    RETURN jsonb_build_object('result', 'off');
END
$$;

REVOKE ALL ON FUNCTION public.rider_set_shift (text, boolean) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.rider_set_shift (p_rider_id text, p_on boolean) IS 'Start (p_on) or end a rider''s shift: only an active rider can start, and nobody can end one during a job.';

-- =============================================================================================
-- OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- Who is in shift right now, by channel:
-- SELECT channel, status, is_in_shift, count(*) FROM rider_master GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
--
-- Switch a rider on as an operator (the same gate the rider gets):
-- SELECT rider_set_shift('447...', true);
