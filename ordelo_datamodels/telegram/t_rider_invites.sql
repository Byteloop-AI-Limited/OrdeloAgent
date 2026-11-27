-- =============================================================================================
-- ordelo_datamodels/telegram/t_rider_invites.sql
-- Personal rider invites: issue, revoke and claim one-time rider bot links, and the durable claim alert queue (take / finish).
-- =============================================================================================
-- LIVE CHECK    pending owner rollout of migrations/telegram_rider_invites.sql (the body below is copied from it byte for byte).
-- OBJECTS       fn     t_rider_invite_issue(p_phone text) -> jsonb
--                   Return the pending personal rider invite, creating a placeholder rider and invite if needed.
--               fn     t_rider_invite_revoke(p_phone text) -> jsonb
--                   Revoke the pending personal rider invite for a phone.
--               fn     t_rider_invite_claim(p_code text, p_update_id bigint, p_tuid bigint, p_tcid bigint, p_username text, p_first_name text) -> jsonb
--                   Claim a personal link and record one durable ops alert.
--               fn     t_rider_invite_alert_take(p_lease uuid) -> jsonb
--                   Lease the next due rider invite alert without returning the bearer code.
--               fn     t_rider_invite_alert_finish(p_update_id bigint, p_lease uuid, p_result text, p_accepted text[]) -> jsonb
--                   Record acceptance, retry or ambiguity for the current alert lease.
-- REQUIRES      telegram/t_invites.sql (rider columns, scope CHECKs and indexes)
--               core/rider_master.sql (invite_profile_update_id)
--               telegram/t_rider_onboarding.sql (t_rider_phone_digits)
--               extension pgcrypto (gen_random_bytes)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE OR REPLACE only. No BEGIN/COMMIT.
--               Apply the REQUIRES files (on live: migrations/telegram_rider_invites.sql) first.
-- SIDE EFFECTS  none when applied (functions only). issue inserts a placeholder rider_master row ('TBD', inactive) if needed.
-- HOW IT FITS   scripts/create_rider_invite.py -> t_rider_invite_issue -> https://t.me/ByteloopRidersBot?start=ri_...
--               /start ri_... -> t_rider_invite_claim (links rider_master and queues the alert in one transaction:
--                 t_invites.rider_alert_next_at = now) -> pg_cron job_rider_invite_alerts (telegram/job_rider_invite_alerts.sql)
--                 -> /rider-hooks/invite-alerts -> invite_alerts.sweep_pending() -> t_rider_invite_alert_take (lease, +2 min)
--                 -> WhatsApp overwatch -> t_rider_invite_alert_finish (accepted | retry +1 min | ambiguous +1 min)
--               Issue, revoke and claim share the per-phone advisory lock 81071 with contact linking.
-- LIFECYCLE     invite: pending -> claimed | revoked.   alert: pending -> sending -> accepted | retry | ambiguous (-> sending ...)
--               RESULT VOCABULARY (jsonb {result, ...})
--                 issue:  ok (+ code) | bad_phone          revoke: ok | bad_phone | no_pending
--                 claim:  ok | replay | unavailable | tuid_taken
--                 take:   ok (+ update_id, phone_tail, tuid, username, previous_tuid, previous_username, accepted) | empty
--                 finish: ok | stale | invalid
-- CALLED BY     t_rider_invite_issue:
--                 python    channels/telegram/rider_invites.py: issue() (from scripts/create_rider_invite.py)
--               t_rider_invite_revoke:
--                 python    channels/telegram/rider_invites.py: revoke()
--               t_rider_invite_claim:
--                 python    channels/telegram/rider_invites.py: claim() (from channels/telegram/rider/router.py)
--               t_rider_invite_alert_take:
--                 python    channels/telegram/rider_invites.py: take_alert() (from channels/telegram/rider/invite_alerts.py)
--               t_rider_invite_alert_finish:
--                 python    channels/telegram/rider_invites.py: finish_alert() (from channels/telegram/rider/invite_alerts.py)
-- PYTHON MODEL  channels/telegram/rider_invites.py (RiderInviteClaim, RiderInviteAlert outcome dataclasses)
-- SECURITY      RLS on t_invites; PUBLIC, anon and authenticated revoked; service role only (client_ordelo_service).
-- TESTS         tests/sql/test_rider_invites_sql.py
--               tests/channels/telegram/test_rider_invite_alerts.py
-- GOTCHAS       take/finish never return invite_code. Transport is at least once: an ambiguous send is retried.
--               Only issue returns the code; never log it or select invite_code when inspecting rider rows.
--               job_rider_invite_alerts() reads the due index only; it calls none of these functions.
-- SEE ALSO      telegram/t_invites.sql
--               telegram/job_rider_invite_alerts.sql
--               telegram/t_rider_onboarding.sql (t_rider_set_invite_profile)
--               plans/telegram-rider-invites.md
--               docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function t_rider_invite_issue(p_phone text) -> jsonb
--   Return the pending personal rider invite for a phone, creating it (and a placeholder rider) when there is none.
--   Arguments: p_phone, the rider's phone in any common format (+, spaces, brackets, dots, dashes); normalised to digits by
--     t_rider_phone_digits(). It must start with a non-zero digit after an optional '+'.
--   Returns {result: 'ok', code}: the one pending rider code for the phone, reused when it exists, otherwise a new
--     'ri_' + 32 URL-safe characters; or {result: 'bad_phone'} when the phone cannot be normalised.
--   Data: takes advisory lock (81071, hashtext(phone)); writes rider_master (inserts rider_id = digits, name / town /
--     vehicle 'TBD', status 'inactive', only when no row exists); reads t_invites (pending rider row for the phone);
--     writes t_invites (new rider row, rest_ref and expires_at NULL; retried on a code collision). Calls gen_random_bytes.
--   Why: one personal link per phone, idempotent so the operator CLI (scripts/create_rider_invite.py) can be re-run to
--     show the same link. This is the only function that returns a code; only the CLI displays it, never log it.
--     The lock is shared with contact linking, claim and revoke, so they cannot interleave for one phone.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function t_rider_invite_revoke(p_phone text) -> jsonb
--   Revoke the pending personal rider invite for a phone. A claimed or already revoked invite is left alone.
--   Arguments: p_phone, normalised as in t_rider_invite_issue().
--   Returns {result}: 'ok' (the pending invite is now revoked) | 'no_pending' (nothing pending for the phone) |
--     'bad_phone' (the phone cannot be normalised).
--   Data: takes advisory lock (81071, hashtext(phone)); writes t_invites.status = 'revoked' on the pending rider row.
--     rider_master is not touched: a placeholder rider stays inactive.
--   Why: operator cleanup of an unused link (for example one sent to the wrong number) without deleting rows; a later
--     issue creates a fresh code.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function t_rider_invite_claim(p_code text, p_update_id bigint, p_tuid bigint, p_tcid bigint, p_username text,
--                                p_first_name text) -> jsonb
--   Claim a personal rider link from the rider bot's /start ri_... and queue one ops alert, in one transaction.
--   Arguments: p_code, the ri_ code from the /start payload; p_update_id, the Telegram update_id (the retry identity);
--     p_tuid / p_tcid, the Telegram user and chat ids; p_username, p_first_name, as Telegram sent them.
--   Returns {result}, never the code:
--     'ok'          the rider is linked and the alert is queued;
--     'replay'      the same update from the same Telegram user already claimed this code (a webhook retry): nothing changes;
--     'unavailable' a missing or malformed argument or code, an unknown, claimed or revoked code, no rider_master row for
--                   the phone, or the update id already used by another claim;
--     'tuid_taken'  this Telegram user is already linked to a different rider.
--   Data: takes advisory lock (81071, hashtext(phone)); reads and locks t_invites and rider_master (FOR UPDATE);
--     writes rider_master (tuid, tcid, t_username, t_first_name, t_linked_at; phone_verified kept only for the same
--     already linked actor; channel 'telegram' on a first link; rider_name from the first name while 'TBD'; while town or
--     vehicle is 'TBD': status 'inactive' and invite_profile_update_id = p_update_id, which t_rider_set_invite_profile()
--     fences on); writes t_invites (status 'claimed', claimed_at, Telegram ids, rider_claim_update_id, the previous
--     Telegram account when the link moves, rider_alert_result 'pending', rider_alert_next_at = now).
--   Why: linking and queueing the alert in one transaction means a crash can never link a rider without telling ops.
--     The update id tells a webhook retry (replay) from a second person using an already claimed link (unavailable).
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function t_rider_invite_alert_take(p_lease uuid) -> jsonb
--   Lease the next due rider invite alert to the caller, without returning the code or the full phone.
--   Arguments: p_lease, a fresh uuid per attempt; it is the fencing token t_rider_invite_alert_finish() checks.
--   Returns {result: 'ok', update_id, phone_tail (last 4 digits), tuid, username, previous_tuid, previous_username,
--     accepted (recipients that already accepted this alert)}; or {result: 'empty'} when nothing is due or p_lease is NULL.
--   Data: reads the earliest due rider row of t_invites (rider_alert_next_at <= now; FOR UPDATE SKIP LOCKED); writes
--     rider_alert_result 'sending', rider_alert_lease = p_lease, rider_alert_next_at = now + 2 minutes, and
--     rider_alert_ambiguous_count + 1 when the previous lease expired while still 'sending'.
--   Why: several app workers (gunicorn) may sweep at once; SKIP LOCKED and the lease keep them off the same alert.
--     A sender that dies loses its lease after 2 minutes, the alert is taken again and counted as ambiguous.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function t_rider_invite_alert_finish(p_update_id bigint, p_lease uuid, p_result text, p_accepted text[]) -> jsonb
--   Record the outcome of one leased send attempt, or reschedule it.
--   Arguments: p_update_id and p_lease, from t_rider_invite_alert_take(); p_result: 'accepted' (the API accepted the send
--     to every pending recipient), 'retry' (failed before any send, for example an empty overwatch list) or 'ambiguous'
--     (at least one send could not be confirmed); p_accepted, the recipients that accepted on this attempt.
--   Returns {result}: 'ok' (recorded) | 'stale' (no rider row with this update id holds this lease: it expired and was
--     taken again, so nothing is written) | 'invalid' (p_result is not one of the three values).
--   Data: writes t_invites: rider_alert_result = p_result, rider_alert_lease = NULL, rider_alert_next_at NULL on
--     'accepted' or now + 1 minute otherwise, rider_alert_accepted = distinct union with p_accepted (so a retry sends
--     only to the rest), rider_alert_ambiguous_count + 1 on 'ambiguous'.
--   Why: the lease is a fencing token, so a late finisher cannot overwrite a newer attempt. 'retry' and 'ambiguous' are
--     sent again a minute later, so the transport is at least once.
-- ---------------------------------------------------------------------------------------------
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
