-- MIGRATION (history; do not edit the statements below after application)
-- Applied to live: pending owner rollout. Tested on throwaway PostgreSQL 17.
-- Current definitions now live in: telegram/t_invites.sql, telegram/t_rider_invites.sql, telegram/t_rider_onboarding.sql,
-- core/rider_master.sql and the restaurant legacy readers named below. Alerts are woken by pg_cron
-- (telegram/job_rider_invite_alerts.sql, ADR 0019), never by an app loop.
-- Purpose: personal one-time rider invites, transactional profile activation and durable claim alerts.
-- Prerequisites: rider Telegram R1, restaurant admin roster P1, rider dashboard cutover (including the
-- rider_master revocation trigger), and pgcrypto. Apply before enabling the CLI or deploying the code.
-- Existing admin rows, expiry defaults and credentials are retained. No historical backfill.
-- Re-running replaces the same constraints in one ALTER and keeps all audit records.

ALTER TABLE public.rider_master ADD COLUMN IF NOT EXISTS invite_profile_update_id bigint;
COMMENT ON COLUMN public.rider_master.invite_profile_update_id IS 'Current rider invite claim permitted to fill the missing profile fields.';

ALTER TABLE public.t_invites
    ALTER COLUMN rest_ref DROP NOT NULL,
    ALTER COLUMN expires_at DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS rider_claim_update_id bigint,
    ADD COLUMN IF NOT EXISTS rider_previous_tuid bigint,
    ADD COLUMN IF NOT EXISTS rider_previous_username text,
    ADD COLUMN IF NOT EXISTS rider_alert_result text,
    ADD COLUMN IF NOT EXISTS rider_alert_next_at timestamptz,
    ADD COLUMN IF NOT EXISTS rider_alert_lease uuid,
    ADD COLUMN IF NOT EXISTS rider_alert_accepted text[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS rider_alert_ambiguous_count integer NOT NULL DEFAULT 0,
    DROP CONSTRAINT IF EXISTS t_invites_bot_scope,
    DROP CONSTRAINT IF EXISTS t_invites_rider_claim_scope,
    ADD CONSTRAINT t_invites_bot_scope CHECK (
        (bot_key = 'rest_admin' AND rest_ref IS NOT NULL AND expires_at IS NOT NULL)
        OR (bot_key = 'rider' AND rest_ref IS NULL AND expires_at IS NULL AND invite_code ~ '^ri_[A-Za-z0-9_-]{32}$')
    ),
    ADD CONSTRAINT t_invites_rider_claim_scope CHECK (
        (rider_claim_update_id IS NOT NULL) = (bot_key = 'rider' AND status = 'claimed')
    );

CREATE UNIQUE INDEX IF NOT EXISTS t_invites_rider_pending_phone_uidx
    ON public.t_invites (phone_number) WHERE bot_key = 'rider' AND status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS t_invites_rider_claim_update_uidx
    ON public.t_invites (rider_claim_update_id) WHERE rider_claim_update_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS t_invites_rider_alert_due_idx
    ON public.t_invites (rider_alert_next_at) WHERE rider_alert_next_at IS NOT NULL;

ALTER TABLE public.t_invites ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.t_invites FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.t_invites TO service_role;

REVOKE ALL ON FUNCTION public.t_new_invite_code (), public.t_invites_normalize_phone () FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE VIEW public.t_invites_shareable WITH ( security_invoker = TRUE
) AS
SELECT
    i.invite_code,
    i.bot_key,
    i.rest_ref,
    i.phone_number,
    i.status,
    i.created_at,
    i.expires_at,
    i.claimed_at,
    i.telegram_user_id,
    i.telegram_chat_id,
    i.telegram_username,
    i.telegram_first_name,
    i.phone_verified,
    ((
            'https://t.me/'::text || c.config_value
) || '?start='::text) || i.invite_code AS invite_link
FROM
    t_invites i
    LEFT JOIN ordelo_config c ON c.config_key::text = (('TGRAM_'::text || upper(i.bot_key)) || '_BOT_USERNAME'::text)
WHERE i.bot_key = 'rest_admin';

REVOKE ALL ON TABLE public.t_invites_shareable FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.t_invites_shareable TO service_role;

-- ---------------------------------------------------------------------------------------------
-- function t_invite_preview(p_code text, p_bot_key text, p_user_id bigint) -> jsonb
--   Read-only: what would happen if this Telegram user used this code (valid, expired, revoked, already yours ...).
--   Data: reads restaurant_master, t_invites.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- t_invite_preview(code, bot_key, telegram_user_id): READ-ONLY classification of an invite for one
-- Telegram user. Called when the person opens the link (/start <code>), before they confirm.
-- Returns jsonb {result, rest_ref, rest_name}; result is one of:
--   unknown         no such code, or the code belongs to a different bot
--   revoked         the operator cancelled it
--   claimed_by_you  already claimed by THIS Telegram user (so pressing the link again is harmless)
--   used            already claimed by someone else
--   expired         past expires_at (or status already 'expired')
--   pending         valid and unclaimed: the bot may ask "Link this chat to <rest_name>?"
-- Never changes data. STABLE so Postgres knows it has no side effects.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_invite_preview (p_code text, p_bot_key text, p_user_id bigint)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public
    AS $$
DECLARE
    r record;
    v_result text;
BEGIN
    -- Join restaurant_master to return the restaurant's display name with the verdict.
    SELECT
        i.*,
        rm.rest_name INTO r
    FROM
        t_invites i
        JOIN restaurant_master rm ON rm.rest_ref = i.rest_ref
    WHERE
        i.invite_code = p_code
        AND i.bot_key = 'rest_admin'
        AND i.bot_key = p_bot_key;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'unknown');
    END IF;
    -- Order matters: a claimed invite is reported as claimed even after its expiry time has passed.
    v_result := CASE WHEN r.status = 'revoked' THEN
        'revoked'
    WHEN r.status = 'claimed'
        AND r.telegram_user_id = p_user_id THEN
        'claimed_by_you'
    WHEN r.status = 'claimed' THEN
        'used'
    WHEN r.status = 'expired'
        OR r.expires_at <= now() THEN
        'expired'
    ELSE
        'pending'
    END;

    RETURN jsonb_build_object('result', v_result, 'rest_ref', r.rest_ref, 'rest_name', r.rest_name);
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- Permissions: Supabase grants new functions and views to the public API roles by default. Remove that;
-- only the service key (used by OrdeloAgent) may call these.
-- ---------------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.t_invite_preview (text, text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_claim_invite(p_code text, p_bot_key text, p_user_id bigint, p_chat_id bigint, p_username text, p_first_name text) -> jsonb
--   Claim an invite atomically for a Telegram user; the first valid caller wins.
--   Data: reads restaurant_master; writes t_invites; calls t_invite_preview().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- t_claim_invite(...): ATOMIC claim, called when the person taps "Yes". The first valid caller wins.
-- Returns the same jsonb shape as the preview, with two extra outcomes:
--   ok              just claimed: telegram_user_id / telegram_chat_id / username / first name / claimed_at
--                   are now stored and status = 'claimed'
--   already_linked  this person already holds another claimed invite for the same restaurant and bot
-- If the invite cannot be claimed it returns the preview verdict (unknown, used, expired, revoked, ...).
-- The single conditional UPDATE below is what makes two people tapping the same link safe: only one
-- row update can match status = 'pending'.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_claim_invite (p_code text, p_bot_key text, p_user_id bigint, p_chat_id bigint, p_username text, p_first_name text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_ref text;
    v_name text;
BEGIN
    UPDATE
        t_invites
    SET
        status = 'claimed',
        claimed_at = now(),
        telegram_user_id = p_user_id,
        telegram_chat_id = p_chat_id,
        telegram_username = p_username,
        telegram_first_name = p_first_name
    WHERE
        invite_code = p_code
        AND bot_key = 'rest_admin'
        AND bot_key = p_bot_key
        AND status = 'pending'
        AND expires_at > now()
    RETURNING
        rest_ref INTO v_ref;

    IF FOUND THEN
        SELECT
            rest_name INTO v_name
        FROM
            restaurant_master
        WHERE
            rest_ref = v_ref;
        RETURN jsonb_build_object('result', 'ok', 'rest_ref', v_ref, 'rest_name', v_name);
    END IF;
    -- Not claimable: record the expiry (the only status change made on a failed attempt), then report why.
    UPDATE
        t_invites
    SET
        status = 'expired'
    WHERE
        invite_code = p_code
        AND bot_key = 'rest_admin'
        AND bot_key = p_bot_key
        AND status = 'pending'
        AND expires_at <= now();
    RETURN t_invite_preview (p_code, p_bot_key, p_user_id);

EXCEPTION
    WHEN unique_violation THEN
        -- Raised by t_invites_one_claim_per_user_rest: this person is already linked to this restaurant.
        -- The whole block (including the UPDATE) is rolled back, so the invite stays 'pending'.
        RETURN jsonb_build_object('result', 'already_linked');
END;

$$;

REVOKE ALL ON FUNCTION public.t_claim_invite (text, text, bigint, bigint, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_linked_restaurants(p_bot_key text, p_user_id bigint) -> jsonb
--   List the restaurants a Telegram user is linked to through claimed invites.
--   Data: reads restaurant_master, t_invites.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- t_linked_restaurants(bot_key, telegram_user_id): the restaurants this Telegram user is currently
-- linked to, as jsonb [{rest_ref, rest_name}, ...] ('[]' if none). Used by /start (no code) and /whoami,
-- and the natural lookup for authorization checks later. Revoked and expired invites do not count.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_linked_restaurants (p_bot_key text, p_user_id bigint)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(jsonb_agg(jsonb_build_object('rest_ref', i.rest_ref, 'rest_name', rm.rest_name)
            ORDER BY rm.rest_name), '[]'::jsonb)
    FROM
        t_invites i
        JOIN restaurant_master rm ON rm.rest_ref = i.rest_ref
    WHERE
        i.bot_key = 'rest_admin'
        AND i.bot_key = p_bot_key
        AND i.telegram_user_id = p_user_id
        AND i.status = 'claimed';
$$;

REVOKE ALL ON FUNCTION public.t_linked_restaurants (text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION public.t_new_invite_code (), public.t_invite_preview (text, text, bigint),
    public.t_claim_invite (text, text, bigint, bigint, text, text), public.t_linked_restaurants (text, bigint) TO service_role;

COMMENT ON TABLE public.t_invites IS 'Personal rider and legacy restaurant-admin invite rows, including claim audit and rider alert state.';
COMMENT ON VIEW public.t_invites_shareable IS 'Legacy restaurant-admin invites and their shareable links.';

-- Issue an invite under the same phone lock used by contact linking, claim and revoke.
-- Returns {result: ok, code} or {result: bad_phone}. Only the CLI should display the code.
CREATE OR REPLACE FUNCTION public.t_rider_invite_issue (p_phone text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, extensions, pg_temp
    AS $$
DECLARE
    v_phone text := t_rider_phone_digits(p_phone);
    v_code text;
BEGIN
    IF v_phone IS NULL OR btrim(p_phone) !~ '^\+?[1-9][0-9 ().-]*$' THEN
        RETURN jsonb_build_object('result', 'bad_phone');
    END IF;
    PERFORM pg_advisory_xact_lock(81071, hashtext(v_phone));
    INSERT INTO rider_master (rider_id, rider_name, town, vehicle_type, status)
        VALUES (v_phone, 'TBD', 'TBD', 'TBD', 'inactive')
        ON CONFLICT (rider_id) DO NOTHING;
    SELECT invite_code INTO v_code
    FROM t_invites
    WHERE bot_key = 'rider' AND phone_number = v_phone AND status = 'pending';
    IF NOT FOUND THEN
        LOOP
            INSERT INTO t_invites (invite_code, bot_key, phone_number, expires_at)
                VALUES ('ri_' || translate(encode(gen_random_bytes(24), 'base64'), '+/', '-_'), 'rider', v_phone, NULL)
                ON CONFLICT (invite_code) DO NOTHING
                RETURNING invite_code INTO v_code;
            EXIT WHEN FOUND;
        END LOOP;
    END IF;
    RETURN jsonb_build_object('result', 'ok', 'code', v_code);
END;
$$;

-- Revoke only a pending rider invite for this phone. Returns ok | bad_phone | no_pending.
CREATE OR REPLACE FUNCTION public.t_rider_invite_revoke (p_phone text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    v_phone text := t_rider_phone_digits(p_phone);
BEGIN
    IF v_phone IS NULL OR btrim(p_phone) !~ '^\+?[1-9][0-9 ().-]*$' THEN
        RETURN jsonb_build_object('result', 'bad_phone');
    END IF;
    PERFORM pg_advisory_xact_lock(81071, hashtext(v_phone));
    UPDATE t_invites SET status = 'revoked'
    WHERE bot_key = 'rider' AND phone_number = v_phone AND status = 'pending';
    RETURN jsonb_build_object('result', CASE WHEN FOUND THEN 'ok' ELSE 'no_pending' END);
END;
$$;

-- Claim and queue the ops alert atomically. The update ID distinguishes a webhook retry
-- (same actor and code) from a fresh attempt using an already claimed invite.
-- Returns ok | replay | unavailable | tuid_taken. Never returns the code.
CREATE OR REPLACE FUNCTION public.t_rider_invite_claim (
    p_code text, p_update_id bigint, p_tuid bigint, p_tcid bigint, p_username text, p_first_name text
)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    i t_invites%ROWTYPE;
    r rider_master%ROWTYPE;
    v_constraint text;
    v_same_actor boolean;
    v_incomplete boolean;
    v_claimed_at timestamptz;
BEGIN
    IF p_update_id IS NULL OR p_tuid IS NULL OR p_tcid IS NULL
        OR p_code IS NULL OR p_code !~ '^ri_[A-Za-z0-9_-]{32}$' THEN
        RETURN jsonb_build_object('result', 'unavailable');
    END IF;
    SELECT * INTO i FROM t_invites WHERE invite_code = p_code AND bot_key = 'rider';
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'unavailable');
    END IF;
    PERFORM pg_advisory_xact_lock(81071, hashtext(i.phone_number));
    SELECT * INTO i FROM t_invites WHERE invite_code = p_code AND bot_key = 'rider' FOR UPDATE;
    IF i.status = 'claimed' AND i.rider_claim_update_id = p_update_id AND i.telegram_user_id = p_tuid THEN
        RETURN jsonb_build_object('result', 'replay');
    END IF;
    IF NOT FOUND OR i.status <> 'pending' THEN
        RETURN jsonb_build_object('result', 'unavailable');
    END IF;

    SELECT * INTO r FROM rider_master WHERE rider_id = i.phone_number FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'unavailable');
    END IF;
    IF EXISTS (SELECT 1 FROM rider_master WHERE tuid = p_tuid AND id <> r.id) THEN
        RETURN jsonb_build_object('result', 'tuid_taken');
    END IF;
    v_same_actor := r.tuid IS NOT DISTINCT FROM p_tuid;
    v_incomplete := r.town = 'TBD' OR r.vehicle_type = 'TBD';
    v_claimed_at := clock_timestamp();

    UPDATE rider_master
    SET tuid = p_tuid, tcid = p_tcid, t_username = p_username, t_first_name = p_first_name,
        t_linked_at = CASE WHEN v_same_actor THEN coalesce(r.t_linked_at, v_claimed_at) ELSE v_claimed_at END,
        phone_verified = v_same_actor AND r.phone_verified AND r.t_linked_at IS NOT NULL,
        channel = CASE WHEN r.tuid IS NULL THEN 'telegram' ELSE r.channel END,
        rider_name = CASE WHEN r.rider_name = 'TBD' THEN coalesce(nullif(btrim(p_first_name), ''), r.rider_name)
                          ELSE r.rider_name END,
        status = CASE WHEN v_incomplete THEN 'inactive' ELSE r.status END,
        invite_profile_update_id = CASE WHEN v_incomplete THEN p_update_id END
    WHERE id = r.id;

    UPDATE t_invites
    SET status = 'claimed', claimed_at = v_claimed_at, telegram_user_id = p_tuid, telegram_chat_id = p_tcid,
        telegram_username = p_username, telegram_first_name = p_first_name, rider_claim_update_id = p_update_id,
        rider_previous_tuid = CASE WHEN NOT v_same_actor THEN r.tuid END,
        rider_previous_username = CASE WHEN NOT v_same_actor AND r.tuid IS NOT NULL THEN r.t_username END,
        rider_alert_result = 'pending', rider_alert_next_at = v_claimed_at
    WHERE invite_code = p_code;

    RETURN jsonb_build_object('result', 'ok');
EXCEPTION
    WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS v_constraint = CONSTRAINT_NAME;
        IF v_constraint = 'rider_master_tuid_uidx' THEN
            RETURN jsonb_build_object('result', 'tuid_taken');
        ELSIF v_constraint = 't_invites_rider_claim_update_uidx' THEN
            RETURN jsonb_build_object('result', 'unavailable');
        END IF;
        RAISE;
END;
$$;

-- Lease one due logical alert. SKIP LOCKED allows concurrent app workers.
-- A lease that expires in flight is observable as ambiguous and the alert is retried.
CREATE OR REPLACE FUNCTION public.t_rider_invite_alert_take (p_lease uuid)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
DECLARE
    i t_invites%ROWTYPE;
BEGIN
    IF p_lease IS NULL THEN
        RETURN jsonb_build_object('result', 'empty');
    END IF;
    SELECT * INTO i FROM t_invites
    WHERE bot_key = 'rider' AND rider_alert_next_at <= clock_timestamp()
    ORDER BY rider_alert_next_at, rider_claim_update_id
    LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'empty');
    END IF;
    UPDATE t_invites
    SET rider_alert_result = 'sending', rider_alert_lease = p_lease,
        rider_alert_next_at = clock_timestamp() + interval '2 minutes',
        rider_alert_ambiguous_count = rider_alert_ambiguous_count + (rider_alert_result = 'sending')::integer
    WHERE rider_claim_update_id = i.rider_claim_update_id;
    RETURN jsonb_build_object('result', 'ok', 'update_id', i.rider_claim_update_id, 'phone_tail', right(i.phone_number, 4),
        'tuid', i.telegram_user_id, 'username', i.telegram_username, 'previous_tuid', i.rider_previous_tuid,
        'previous_username', i.rider_previous_username, 'accepted', i.rider_alert_accepted);
END;
$$;

-- Complete or reschedule the alert using the current lease as a fencing token.
-- 'accepted' means API acceptance, 'retry' means failure before a send, and 'ambiguous' means at least one
-- send could not be confirmed. The latter can retry, so the transport is at least once.
CREATE OR REPLACE FUNCTION public.t_rider_invite_alert_finish (
    p_update_id bigint, p_lease uuid, p_result text, p_accepted text[]
)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
BEGIN
    IF p_result IS NULL OR p_result NOT IN ('accepted', 'retry', 'ambiguous') THEN
        RETURN jsonb_build_object('result', 'invalid');
    END IF;
    UPDATE t_invites
    SET rider_alert_result = p_result, rider_alert_lease = NULL,
        rider_alert_next_at = CASE WHEN p_result <> 'accepted' THEN clock_timestamp() + interval '1 minute' END,
        rider_alert_accepted = ARRAY(SELECT DISTINCT unnest(rider_alert_accepted || coalesce(p_accepted, '{}'))),
        rider_alert_ambiguous_count = rider_alert_ambiguous_count + (p_result = 'ambiguous')::integer
    WHERE bot_key = 'rider' AND rider_claim_update_id = p_update_id AND rider_alert_lease = p_lease;
    RETURN jsonb_build_object('result', CASE WHEN FOUND THEN 'ok' ELSE 'stale' END);
END;
$$;

REVOKE ALL ON FUNCTION public.t_rider_invite_issue (text), public.t_rider_invite_revoke (text),
    public.t_rider_invite_claim (text, bigint, bigint, bigint, text, text),
    public.t_rider_invite_alert_take (uuid), public.t_rider_invite_alert_finish (bigint, uuid, text, text[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.t_rider_invite_issue (text), public.t_rider_invite_revoke (text),
    public.t_rider_invite_claim (text, bigint, bigint, bigint, text, text),
    public.t_rider_invite_alert_take (uuid), public.t_rider_invite_alert_finish (bigint, uuid, text, text[])
    TO service_role;

COMMENT ON FUNCTION public.t_rider_invite_issue (text) IS 'Return the pending personal rider invite, creating a placeholder rider and invite if needed.';
COMMENT ON FUNCTION public.t_rider_invite_revoke (text) IS 'Revoke the pending personal rider invite for a phone.';
COMMENT ON FUNCTION public.t_rider_invite_claim (text, bigint, bigint, bigint, text, text) IS 'Claim a personal link and record one durable ops alert.';
COMMENT ON FUNCTION public.t_rider_invite_alert_take (uuid) IS 'Lease the next due rider invite alert without returning the bearer code.';
COMMENT ON FUNCTION public.t_rider_invite_alert_finish (bigint, uuid, text, text[]) IS 'Record acceptance, retry or ambiguity for the current alert lease.';

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
    PERFORM pg_advisory_xact_lock(81071, hashtext(v_phone));
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
            is_in_shift = TRUE,
            invite_profile_update_id = NULL
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
            t_first_name = p_first_name,
            phone_verified = TRUE,
            t_linked_at = coalesce(v_row.t_linked_at, clock_timestamp())
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
            invite_profile_update_id = NULL,
            channel = 'telegram'
        WHERE
            id = v_row.id
        RETURNING
            * INTO v_row;
        v_result := 'relinked';
    END IF;
    RETURN jsonb_build_object('result', v_result, 'rider_id', v_row.rider_id, 'rider_name', v_row.rider_name, 'status', v_row.status, 'town', v_row.town, 'vehicle_type', v_row.vehicle_type, 'needs_profile', (v_row.town = 'TBD' OR v_row.vehicle_type = 'TBD'), 'invite_claim', v_row.invite_profile_update_id, 'previous_tuid', v_prev_tuid, 'previous_username', v_prev_username);
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
-- function t_rider_set_invite_profile(p_tuid bigint, p_town text, p_vehicle_type text, p_claim_update_id bigint) -> jsonb
--   Fill the town and/or vehicle of the rider linked to p_tuid. A NULL argument leaves that value alone. A value is
--   accepted only if t_rider_choices() lists it (towns case-insensitively; the listed spelling is stored), and only while the
--   stored value is still 'TBD': an operator-set town or vehicle is never changed from the bot (locked).
--   An invite profile requires the claim reference on the current rider row, and activates on the final choice.
--   Returns {result, town, vehicle_type, needs_profile, status}, or stale when the claim no longer matches.
--   Data: reads/writes rider_master; calls t_rider_choices().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_rider_set_invite_profile (p_tuid bigint, p_town text, p_vehicle_type text, p_claim_update_id bigint)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_row rider_master%ROWTYPE;
    v_choices jsonb := t_rider_choices ();
    v_town text;
    v_vehicle text;
    v_complete boolean;
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
    IF v_row.invite_profile_update_id IS DISTINCT FROM p_claim_update_id THEN
        RETURN jsonb_build_object('result', 'stale');
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
    v_complete := coalesce(v_town, v_row.town) <> 'TBD' AND coalesce(v_vehicle, v_row.vehicle_type) <> 'TBD'
        AND ((v_town IS NOT NULL AND v_row.town = 'TBD') OR (v_vehicle IS NOT NULL AND v_row.vehicle_type = 'TBD'));
    UPDATE
        rider_master
    SET
        town = coalesce(v_town, town),
        vehicle_type = coalesce(v_vehicle, vehicle_type),
        status = CASE WHEN p_claim_update_id IS NOT NULL AND v_complete AND status = 'inactive' THEN 'active' ELSE status END,
        invite_profile_update_id = CASE WHEN v_complete THEN NULL ELSE invite_profile_update_id END
    WHERE
        id = v_row.id
    RETURNING
        * INTO v_row;
    RETURN jsonb_build_object('result', 'ok', 'town', v_row.town, 'vehicle_type', v_row.vehicle_type, 'needs_profile', (v_row.town = 'TBD' OR v_row.vehicle_type = 'TBD'), 'status', v_row.status);
END;
$$;

-- Ordinary contact sign-up uses the same choice validation; it retains operator activation.
CREATE OR REPLACE FUNCTION public.t_rider_set_profile (p_tuid bigint, p_town text, p_vehicle_type text)
    RETURNS jsonb
    LANGUAGE sql
    SET search_path = public, pg_temp
    AS $$
    SELECT public.t_rider_set_invite_profile(p_tuid, p_town, p_vehicle_type, NULL) - 'status';
$$;

REVOKE ALL ON FUNCTION public.t_rider_set_invite_profile (bigint, text, text, bigint) FROM PUBLIC, anon, authenticated;
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
                jsonb_build_object('result', 'ok', 'rider_id', r.rider_id, 'rider_name', r.rider_name, 'status', r.status, 'town', r.town, 'vehicle_type', r.vehicle_type, 'channel', r.channel, 'is_in_shift', r.is_in_shift, 'tcid', r.tcid, 'invite_claim', r.invite_profile_update_id, 'phone_verified', (r.phone_verified AND r.t_linked_at IS NOT NULL), 'needs_profile', (r.town = 'TBD' OR r.vehicle_type = 'TBD'))
            FROM rider_master r
            WHERE
                r.tuid = p_tuid), jsonb_build_object('result', 'not_linked'));
$$;

REVOKE ALL ON FUNCTION public.t_rider_profile (bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION public.t_rider_phone_digits (text), public.t_rider_link (bigint, bigint, text, text, text),
    public.t_rider_choices (), public.t_rider_set_profile (bigint, text, text),
    public.t_rider_set_invite_profile (bigint, text, text, bigint), public.t_rider_profile (bigint) TO service_role;

-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.t_rider_phone_digits (p_phone text) IS 'Normalise a phone number to digits only; NULL when it cannot be a rider_id.';

COMMENT ON FUNCTION public.t_rider_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) IS 'Link this Telegram account to the rider with this (verified) phone, move an older link, or register a new rider.';

COMMENT ON FUNCTION public.t_rider_choices () IS 'The towns and vehicle types a sign-up can pick: distinct values already in rider_master (never TBD).';

COMMENT ON FUNCTION public.t_rider_set_profile (p_tuid bigint, p_town text, p_vehicle_type text) IS 'Store the town and/or vehicle a new rider picked; only fills values that are still TBD.';

COMMENT ON FUNCTION public.t_rider_set_invite_profile (bigint, text, text, bigint) IS 'Apply a choice for the current invite claim and activate on completion.';

COMMENT ON FUNCTION public.t_rider_profile (p_tuid bigint) IS 'Who this Telegram account is as a rider; read-only.';

-- restaurant_admin/admin_roster.sql: isolate the legacy restaurant readers from rider invite rows.
CREATE OR REPLACE FUNCTION public.admin_roster_status (p_rest_ref text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(jsonb_agg(jsonb_build_object(
            'raw', a.raw, 'phone', p.phone, 'valid', p.phone IS NOT NULL,
            'linked', ra.tuid IS NOT NULL, 't_username', ra.t_username, 't_first_name', ra.t_first_name,
            't_linked_at', ra.t_linked_at,
            'channels', to_jsonb(coalesce(ra.channels, ARRAY['whatsapp']::text[])),
            'paused', p.phone IS NOT NULL AND public.is_paused ('rest_admin', p.phone, rm.rest_ref),
            'legacy_invite', ra.phone IS NULL AND EXISTS (SELECT 1 FROM public.t_invites i
                                      WHERE i.bot_key = 'rest_admin' AND i.rest_ref = rm.rest_ref AND i.status = 'claimed'
                                        AND public.admin_phone_digits (i.phone_number) = p.phone))
            ORDER BY a.ord), '[]'::jsonb)
    FROM
        public.restaurant_master rm
        CROSS JOIN LATERAL unnest(coalesce(rm.admins, '{}'::text[])) WITH ORDINALITY AS a (raw, ord)
        CROSS JOIN LATERAL (SELECT public.admin_phone_digits (a.raw) AS phone) p
        LEFT JOIN public.restaurant_admin ra ON ra.phone = p.phone
    WHERE
        rm.rest_ref = p_rest_ref
$$;
REVOKE ALL ON FUNCTION public.admin_roster_status (text) FROM PUBLIC, anon, authenticated;

-- restaurant_admin/restaurant_order_decision.sql: isolate the legacy restaurant readers from rider invite rows.
CREATE OR REPLACE FUNCTION public.restaurant_admin_label (p_phone text)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce((
            SELECT
                ra.t_first_name
            FROM
                public.restaurant_admin ra
            WHERE
                ra.phone = public.admin_phone_digits (p_phone)
                AND ra.t_first_name IS NOT NULL),
            -- TRANSITION (P3 removes)
            (
                SELECT
                    i.telegram_first_name
                FROM
                    public.t_invites i
                WHERE
                    i.phone_number = p_phone
                    AND i.bot_key = 'rest_admin'
                    AND i.status = 'claimed'
                    AND i.telegram_first_name IS NOT NULL
                ORDER BY
                    i.claimed_at DESC
                LIMIT 1),
            CASE WHEN coalesce(p_phone, '') = '' THEN
                NULL
            ELSE
                '…' || RIGHT (p_phone, 4)
            END)
$$;
REVOKE ALL ON FUNCTION public.restaurant_admin_label (text) FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.t_order_admin_phone (p_bot_key text, p_tuid bigint, p_rest_ref text)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(public.admin_for_tuid (p_tuid, p_rest_ref),
            -- TRANSITION (P3 removes): invite-linked admins whose phone has no admin record
            (
                SELECT
                    r.phone
                FROM
                    public.t_invites i
                    JOIN public.admin_roster r ON r.rest_ref = i.rest_ref
                        AND r.phone = public.admin_phone_digits (i.phone_number)
                WHERE
                    i.bot_key = p_bot_key
                    AND i.bot_key = 'rest_admin'
                    AND i.telegram_user_id = p_tuid
                    AND i.rest_ref = p_rest_ref
                    AND i.status = 'claimed'
                    AND NOT EXISTS (
                        SELECT
                            1
                        FROM
                            public.restaurant_admin ra
                        WHERE
                            ra.phone = r.phone)
                ORDER BY
                    i.claimed_at DESC NULLS LAST
                LIMIT 1))
$$;
REVOKE ALL ON FUNCTION public.t_order_admin_phone (text, bigint, text) FROM PUBLIC, anon, authenticated;

-- telegram/t_order_alerts.sql: isolate the legacy restaurant readers from rider invite rows.
CREATE OR REPLACE FUNCTION public.t_order_card_destinations (p_bot_key text, p_rest_ref text)
    RETURNS TABLE (
        tcid bigint,
        tuid bigint,
        phone text,
        label text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT DISTINCT ON (x.tcid)
        x.tcid,
        x.tuid,
        x.phone,
        x.label
    FROM (
        SELECT
            r.tcid,
            r.tuid,
            r.phone,
            r.t_first_name AS label,
            1 AS pri,
            r.t_linked_at AS at
        FROM
            public.admin_roster r
        WHERE
            r.rest_ref = p_rest_ref
            AND r.tcid IS NOT NULL
        UNION ALL
        -- TRANSITION (P3 removes): claimed invites of listed phones that have no admin record yet
        SELECT
            i.telegram_chat_id,
            i.telegram_user_id,
            r.phone,
            i.telegram_first_name,
            2,
            i.claimed_at
        FROM
            public.t_invites i
            JOIN public.admin_roster r ON r.rest_ref = i.rest_ref
                AND r.phone = public.admin_phone_digits (i.phone_number)
        WHERE
            i.bot_key = p_bot_key
            AND i.bot_key = 'rest_admin'
            AND i.rest_ref = p_rest_ref
            AND i.status = 'claimed'
            AND i.telegram_chat_id IS NOT NULL
            AND NOT EXISTS (
                SELECT
                    1
                FROM
                    public.restaurant_admin ra
                WHERE
                    ra.phone = r.phone)) x
    ORDER BY
        x.tcid,
        x.pri,
        x.at DESC NULLS LAST
$$;
REVOKE ALL ON FUNCTION public.t_order_card_destinations (text, text) FROM PUBLIC, anon, authenticated;

-- telegram/t_admin_pauses.sql: isolate the legacy restaurant readers from rider invite rows.
CREATE OR REPLACE FUNCTION public.t_admin_restaurants (p_bot_key text, p_tuid bigint)
    RETURNS TABLE (
        rest_ref text,
        rest_name text,
        phone text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        r.rest_ref::text,
        r.rest_name,
        r.phone
    FROM
        public.admin_roster r
    WHERE
        r.tuid = p_tuid
    UNION
    -- TRANSITION (P3 removes): invite-linked admins with no admin record
    SELECT
        i.rest_ref::text,
        rm.rest_name,
        public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref)
    FROM
        public.t_invites i
        JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
    WHERE
        i.bot_key = p_bot_key
        AND i.bot_key = 'rest_admin'
        AND i.telegram_user_id = p_tuid
        AND i.status = 'claimed'
        AND public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) IS NOT NULL
$$;
REVOKE ALL ON FUNCTION public.t_admin_restaurants (text, bigint) FROM PUBLIC, anon, authenticated;
