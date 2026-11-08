-- =============================================================================================
-- ordelo_datamodels/telegram/t_rider_onboarding.sql
-- Rider bot onboarding: link a Telegram account to rider_master by a shared, verified phone number, or register a new rider.
-- =============================================================================================
-- LIVE CHECK    Live since 2026-10-22 (migrations/rider_telegram_r1.sql step 4); onboarding tested live the same day.
-- OBJECTS       fn     t_rider_phone_digits(p_phone text) -> text
--                   Normalise a phone number to digits only (Telegram sends '+44...' or '44...'); NULL when it cannot be a rider_id.
--               fn     t_rider_link(p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) -> jsonb
--                   Link this Telegram account to the rider with this (verified) phone, move an older link, or register a new rider.
--               fn     t_rider_set_profile(p_tuid bigint, p_town text, p_vehicle_type text) -> jsonb
--                   Store the town and/or vehicle a new rider picked; only fills values that are still 'TBD'.
--               fn     t_rider_choices() -> jsonb
--                   The towns and vehicle types a sign-up can pick: distinct values already in rider_master (never 'TBD').
--               fn     t_rider_profile(p_tuid bigint) -> jsonb
--                   Who this Telegram account is as a rider (rider_id, name, status, town, vehicle, channel, shift); read-only.
-- REQUIRES      core/rider_master.sql
--               migrations/rider_telegram_r1.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (functions only).
-- HOW IT FITS   Generic invite: everybody gets the same link t.me/ByteloopRidersBot?start=join (no per-phone invite rows, D39).
--                 /start -> the bot asks for the phone with Telegram's "Share my phone number" button -> the router accepts the
--                 contact ONLY when contact.user_id == from_user.id (the number is the sender's own, as Telegram registered it)
--                 -> t_rider_link(). Typed numbers are never accepted. Unknown phone -> a new rider_master row
--                 (status 'inactive', town/vehicle 'TBD') -> the bot offers t_rider_choices() as buttons ->
--                 t_rider_set_profile() -> "Thanks, Byteloop will activate your account". An operator activates by setting
--                 status = 'active'; until then get_available_riders() never offers the rider a job (D41).
--                 The phone is never carried in callback data: after the contact step every call is keyed by tuid, which
--                 Telegram supplies and the bot cannot be tricked into changing.
--                 Python: channels/telegram/rider_links.py (wrapper), channels/telegram/rider/router.py (handlers).
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 t_rider_link:        linked          existing rider, was not linked; now linked (channel -> 'telegram')
--                                      relinked        existing rider linked to ANOTHER Telegram account; link moved here
--                                                      (previous_tuid / previous_username returned for the ops alert, D42)
--                                      already_linked  same rider, same account; tcid / username / first name refreshed
--                                      registered      unknown phone: new rider row, status 'inactive', town/vehicle 'TBD'
--                                      tuid_taken      this Telegram account is linked to a DIFFERENT rider row: refused (D42)
--                                      bad_phone       the number cannot be a rider_id (not 8-12 digits)
--                 Every non-error result carries the rider snapshot: rider_id, rider_name, status, town, vehicle_type,
--                 needs_profile (town or vehicle still 'TBD').
--                 t_rider_set_profile: ok | not_linked | bad_town | bad_vehicle | locked (the value is no longer 'TBD')
--                 t_rider_profile:     ok | not_linked
-- CALLED BY     t_rider_phone_digits:
--                 sql       t_rider_link() (telegram/t_rider_onboarding.sql)
--               t_rider_link:
--                 python    channels/telegram/rider_links.py: link()
--               t_rider_set_profile:
--                 python    channels/telegram/rider_links.py: set_profile()
--               t_rider_choices:
--                 sql       t_rider_set_profile() (telegram/t_rider_onboarding.sql)
--                 python    channels/telegram/rider_links.py: choices()
--               t_rider_profile:
--                 python    channels/telegram/rider_links.py: profile()
-- PYTHON MODEL  channels/telegram/rider_links.py (RiderLink, RiderChoices outcome dataclasses)
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated; called with client_ordelo_service only.
-- TESTS         tests/sql/test_rider_onboarding_sql.py
--               tests/channels/telegram/test_rider_router.py
--               tests/channels/telegram/test_rider_links.py
-- GOTCHAS       rider_master has RLS OFF (see core/rider_master.sql): these functions are the only intended writers of the
--                 Telegram columns, but a direct anon write is not blocked until the security review lands (docs/to-do.md).
--               A Telegram contact's phone_number may start with '+' or not; t_rider_phone_digits() strips everything that is
--                 not a digit. UK numbers arrive as 44..., which matches how rider_id is stored today.
--               Moving a link (relinked) does NOT notify the old chat: the old account can no longer prove the number.
-- SEE ALSO      core/rider_master.sql
--               telegram/t_invites.sql
--               test_support/test_rider_onboarding.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function t_rider_phone_digits(p_phone text) -> text
--   Digits only; NULL when the result is not 8-12 digits long (rider_id is varchar(12)).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_phone_digits (p_phone text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        CASE WHEN length(regexp_replace(coalesce(p_phone, ''), '[^0-9]', '', 'g')) BETWEEN 8 AND 12 THEN
            regexp_replace(p_phone, '[^0-9]', '', 'g')
        END;
$$;

REVOKE ALL ON FUNCTION public.t_rider_phone_digits (text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_rider_link(p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) -> jsonb
--   Called once the rider bot has checked contact.user_id == from_user.id. Decides every case in one transaction:
--     1. p_tuid already linked to a DIFFERENT rider_id          -> tuid_taken (nothing changes)
--     2. phone found, not linked                                -> linked   (channel 'telegram', is_in_shift true, phone_verified)
--     3. phone found, linked to p_tuid                          -> already_linked (tcid / username / first name refreshed)
--     4. phone found, linked to another Telegram account        -> relinked (the link moves; previous_* returned)
--     5. phone not found                                        -> registered (new row: status 'inactive', town/vehicle 'TBD')
--   The rider row is locked FOR UPDATE, so two taps at once cannot both win. A concurrent first insert of the same phone
--   (ON CONFLICT DO NOTHING finds nothing to return) is resolved by running the decision again on the row that now exists.
--   Data: reads/writes rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_phone text := t_rider_phone_digits (p_phone);
    v_row rider_master%ROWTYPE;
    v_other text;
    v_result text;
    v_prev_tuid bigint;
    v_prev_username text;
BEGIN
    IF v_phone IS NULL OR p_tuid IS NULL OR p_tcid IS NULL THEN
        RETURN jsonb_build_object('result', 'bad_phone');
    END IF;
    -- 1. This Telegram account already belongs to another rider row: a human decides (D42).
    SELECT
        rider_id INTO v_other
    FROM
        rider_master
    WHERE
        tuid = p_tuid
        AND rider_id <> v_phone;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'tuid_taken', 'rider_id', v_other);
    END IF;
    SELECT
        * INTO v_row
    FROM
        rider_master
    WHERE
        rider_id = v_phone
    FOR UPDATE;
    IF NOT FOUND THEN
        -- 5. Unknown phone: register an inactive rider. is_in_shift keeps its column default; status is the gate (D41).
        INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, channel, tuid, tcid, t_username, t_first_name, t_linked_at, phone_verified)
            VALUES (v_phone, coalesce(nullif(btrim(p_first_name), ''), 'TBD'), 'TBD', 'TBD', 'inactive', 'telegram', p_tuid, p_tcid, p_username, p_first_name, now(), TRUE)
        ON CONFLICT (rider_id)
            DO NOTHING
        RETURNING
            * INTO v_row;
        IF NOT FOUND THEN
            RETURN t_rider_link (p_tuid, p_tcid, p_phone, p_username, p_first_name);
        END IF;
        v_result := 'registered';
    ELSIF v_row.tuid IS NULL THEN
        -- 2. First link for an existing rider.
        UPDATE
            rider_master
        SET
            tuid = p_tuid,
            tcid = p_tcid,
            t_username = p_username,
            t_first_name = p_first_name,
            t_linked_at = now(),
            phone_verified = TRUE,
            channel = 'telegram',
            is_in_shift = TRUE
        WHERE
            id = v_row.id
        RETURNING
            * INTO v_row;
        v_result := 'linked';
    ELSIF v_row.tuid = p_tuid THEN
        -- 3. Same person again: refresh where we send and how we show them.
        UPDATE
            rider_master
        SET
            tcid = p_tcid,
            t_username = p_username,
            t_first_name = p_first_name
        WHERE
            id = v_row.id
        RETURNING
            * INTO v_row;
        v_result := 'already_linked';
    ELSE
        -- 4. Another Telegram account now proves this number: move the link (D42).
        v_prev_tuid := v_row.tuid;
        v_prev_username := v_row.t_username;
        UPDATE
            rider_master
        SET
            tuid = p_tuid,
            tcid = p_tcid,
            t_username = p_username,
            t_first_name = p_first_name,
            t_linked_at = now(),
            phone_verified = TRUE,
            channel = 'telegram'
        WHERE
            id = v_row.id
        RETURNING
            * INTO v_row;
        v_result := 'relinked';
    END IF;
    RETURN jsonb_build_object('result', v_result, 'rider_id', v_row.rider_id, 'rider_name', v_row.rider_name, 'status', v_row.status, 'town', v_row.town, 'vehicle_type', v_row.vehicle_type, 'needs_profile', (v_row.town = 'TBD' OR v_row.vehicle_type = 'TBD'), 'previous_tuid', v_prev_tuid, 'previous_username', v_prev_username);
EXCEPTION
    WHEN unique_violation THEN
        -- rider_master_tuid_uidx: the same Telegram account was linked to another row by a concurrent call.
        RETURN jsonb_build_object('result', 'tuid_taken');
END;

$$;

REVOKE ALL ON FUNCTION public.t_rider_link (bigint, bigint, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_rider_choices() -> jsonb
--   {"towns": [...], "vehicle_types": [...]}: the distinct values already in rider_master, sorted, never 'TBD'.
--   Towns are de-duplicated case-insensitively (dispatch compares LOWER(town)); the first spelling alphabetically is shown.
--   Data: reads rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_choices ()
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        jsonb_build_object('towns', coalesce((
                SELECT
                    jsonb_agg(t.town ORDER BY lower(t.town))
                FROM (SELECT DISTINCT ON (lower(btrim(town)))
                        btrim(town) AS town
                    FROM rider_master
                    WHERE
                        btrim(town) <> ''
                        AND upper(btrim(town)) <> 'TBD'
                    ORDER BY lower(btrim(town)), btrim(town)) t), '[]'::jsonb), 'vehicle_types', coalesce((
                SELECT
                    jsonb_agg(v.vehicle_type ORDER BY v.vehicle_type)
                FROM (SELECT DISTINCT
                        btrim(vehicle_type) AS vehicle_type
                    FROM rider_master
                    WHERE
                        btrim(vehicle_type) <> ''
                        AND upper(btrim(vehicle_type)) <> 'TBD') v), '[]'::jsonb));
$$;

REVOKE ALL ON FUNCTION public.t_rider_choices () FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_rider_set_profile(p_tuid bigint, p_town text, p_vehicle_type text) -> jsonb
--   Fill the town and/or vehicle of the rider linked to p_tuid. A NULL argument leaves that value alone. A value is
--   accepted only if t_rider_choices() lists it (towns case-insensitively; the listed spelling is stored), and only while the
--   stored value is still 'TBD': an operator-set town or vehicle is never changed from the bot (locked).
--   Returns {result, town, vehicle_type, needs_profile}.
--   Data: reads/writes rider_master; calls t_rider_choices().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_set_profile (p_tuid bigint, p_town text, p_vehicle_type text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_row rider_master%ROWTYPE;
    v_choices jsonb := t_rider_choices ();
    v_town text;
    v_vehicle text;
BEGIN
    SELECT
        * INTO v_row
    FROM
        rider_master
    WHERE
        tuid = p_tuid
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    IF p_town IS NOT NULL THEN
        SELECT
            t INTO v_town
        FROM
            jsonb_array_elements_text(v_choices -> 'towns') t
        WHERE
            lower(t) = lower(btrim(p_town));
        IF v_town IS NULL THEN
            RETURN jsonb_build_object('result', 'bad_town');
        END IF;
        IF v_row.town <> 'TBD' AND lower(v_row.town) <> lower(v_town) THEN
            RETURN jsonb_build_object('result', 'locked', 'town', v_row.town, 'vehicle_type', v_row.vehicle_type);
        END IF;
    END IF;
    IF p_vehicle_type IS NOT NULL THEN
        SELECT
            v INTO v_vehicle
        FROM
            jsonb_array_elements_text(v_choices -> 'vehicle_types') v
        WHERE
            v = btrim(p_vehicle_type);
        IF v_vehicle IS NULL THEN
            RETURN jsonb_build_object('result', 'bad_vehicle');
        END IF;
        IF v_row.vehicle_type <> 'TBD' AND v_row.vehicle_type <> v_vehicle THEN
            RETURN jsonb_build_object('result', 'locked', 'town', v_row.town, 'vehicle_type', v_row.vehicle_type);
        END IF;
    END IF;
    UPDATE
        rider_master
    SET
        town = coalesce(v_town, town),
        vehicle_type = coalesce(v_vehicle, vehicle_type)
    WHERE
        id = v_row.id
    RETURNING
        * INTO v_row;
    RETURN jsonb_build_object('result', 'ok', 'town', v_row.town, 'vehicle_type', v_row.vehicle_type, 'needs_profile', (v_row.town = 'TBD' OR v_row.vehicle_type = 'TBD'));
END;
$$;

REVOKE ALL ON FUNCTION public.t_rider_set_profile (bigint, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_rider_profile(p_tuid bigint) -> jsonb
--   The rider linked to this Telegram account, or {result: 'not_linked'}. Read-only; used by /start (no contact yet),
--   /whoami and, from phase R4, to resolve the actor of every rider bot action.
--   Data: reads rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_profile (p_tuid bigint)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce((
            SELECT
                jsonb_build_object('result', 'ok', 'rider_id', r.rider_id, 'rider_name', r.rider_name, 'status', r.status, 'town', r.town, 'vehicle_type', r.vehicle_type, 'channel', r.channel, 'is_in_shift', r.is_in_shift, 'tcid', r.tcid, 'needs_profile', (r.town = 'TBD' OR r.vehicle_type = 'TBD'))
            FROM rider_master r
            WHERE
                r.tuid = p_tuid), jsonb_build_object('result', 'not_linked'));
$$;

REVOKE ALL ON FUNCTION public.t_rider_profile (bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.t_rider_phone_digits (p_phone text) IS 'Normalise a phone number to digits only; NULL when it cannot be a rider_id.';

COMMENT ON FUNCTION public.t_rider_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) IS 'Link this Telegram account to the rider with this (verified) phone, move an older link, or register a new rider.';

COMMENT ON FUNCTION public.t_rider_choices () IS 'The towns and vehicle types a sign-up can pick: distinct values already in rider_master (never TBD).';

COMMENT ON FUNCTION public.t_rider_set_profile (p_tuid bigint, p_town text, p_vehicle_type text) IS 'Store the town and/or vehicle a new rider picked; only fills values that are still TBD.';

COMMENT ON FUNCTION public.t_rider_profile (p_tuid bigint) IS 'Who this Telegram account is as a rider; read-only.';

-- =============================================================================================
-- OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- Riders who signed up on Telegram and wait for activation:
-- SELECT rider_id, rider_name, town, vehicle_type, t_username, t_linked_at FROM rider_master
--  WHERE status = 'inactive' AND tuid IS NOT NULL ORDER BY t_linked_at DESC;
--
-- Activate one (they get jobs from the next dispatch run):
-- UPDATE rider_master SET status = 'active' WHERE rider_id = '447...' RETURNING rider_id, status, town, vehicle_type;
--
-- Put a linked rider back on WhatsApp (takes effect from the next offer, D44):
-- UPDATE rider_master SET channel = 'whatsapp' WHERE rider_id = '447...' RETURNING rider_id, channel;
--
-- Unlink a Telegram account (the rider can link again with /start):
-- UPDATE rider_master SET tuid = NULL, tcid = NULL, channel = 'whatsapp' WHERE rider_id = '447...' RETURNING rider_id;
