-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/admin_roster.sql
-- Admin roster: who a restaurant's admins are, which channels each one hears on, and the phone-verified Telegram link.
-- =============================================================================================
-- LIVE CHECK    NOT YET APPLIED. Written for plans/restaurant-admin-roster-onboarding-plan.md (P1); the owner applies it with
--               migrations/admin_roster_p1.sql and runs test_support/test_admin_onboarding.sql.
-- OBJECTS       fn     admin_phone_digits(p_phone text) -> text
--                   Digits only; NULL unless 8-15 digits. The one phone rule of the roster.
--               table  restaurant_admin
--                   The admin record: one row per phone (channels, Telegram link). Confers no authority (D3).
--               view   admin_roster
--                   One row per (restaurant, phone) on a restaurant's admin list, with that phone's admin record.
--               fn     admin_recipients(p_rest_ref text, p_channel text) -> TABLE(phone text, tcid bigint, tuid bigint, label text)
--                   Who gets a NEW message on this channel: on the list, channel chosen, not paused, (Telegram) linked.
--               fn     admin_for_tuid(p_tuid bigint, p_rest_ref text) -> text
--                   The admin phone of this Telegram user for this restaurant, else NULL.
--               fn     t_admin_link(p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) -> jsonb
--                   Link a Telegram account to an admin phone (the phone was shared by the sender, never typed).
--               fn     t_admin_profile(p_tuid bigint) -> jsonb
--                   Who this Telegram account is as an admin (phone, channels, restaurants); read-only.
--               fn     admin_set_channels(p_phone text, p_channels text[], p_by text) -> jsonb
--                   Change where an admin's messages go.
--               fn     admin_unlink_telegram(p_phone text, p_by text) -> jsonb
--                   Clear the Telegram link; the admin goes back to WhatsApp only.
--               fn     admin_roster_status(p_rest_ref text) -> jsonb
--                   One restaurant's admin list with link and channel state, for the sys-admin page.
-- REQUIRES      core/restaurant_master.sql
--               availability/pauses.sql
--               telegram/t_invites.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Creates the table restaurant_admin (empty) and one ordelo_config row (ON CONFLICT DO NOTHING).
-- HOW IT FITS   restaurant_master.admins stays the authority on WHO is an admin of a restaurant (D3). restaurant_admin holds
--                 what is true of the PERSON (phone): the Telegram account that proved the number and the channels they
--                 want. A restaurant owner opens the restaurant bot, shares their own phone number with Telegram's button;
--                 the router accepts it only when contact.user_id == from_user.id and calls t_admin_link(). A phone that is
--                 on no restaurant's list is refused (not_on_roster), so a stranger who shares a number gets nothing.
--                 Linking moves the admin to Telegram only (D6); admin_set_channels() can put WhatsApp back.
--                 The t_* destination functions (telegram/t_order_alerts.sql, restaurant_admin/restaurant_order_decision.sql,
--                 telegram/t_admin_pauses.sql) read admin_roster; while an admin has no record they keep reading claimed
--                 invites (TRANSITION branches, removed in P3).
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 t_admin_link:          linked          first link for this phone; channels := {telegram}
--                                        relinked        another Telegram account proved this phone; link moved (previous_tuid /
--                                                        previous_username returned for the ops alert)
--                                        already_linked  same phone, same account; chat / username / first name refreshed
--                                        not_on_roster   the phone is on no restaurant's admin list; nothing written
--                                        tuid_taken      this Telegram account is linked to a DIFFERENT phone; refused
--                                        bad_phone       not 8-15 digits, or ids missing
--                 t_admin_profile:       ok | not_linked | not_on_roster
--                 admin_set_channels:    ok | not_found | bad_channels | not_linked
--                 admin_unlink_telegram: ok | not_found | not_linked
-- CALLED BY     admin_phone_digits:
--                 sql       admin_roster, t_admin_link(), admin_roster_status(), admin_set_channels(), admin_unlink_telegram(),
--                           t_order_card_destinations(), t_order_admin_phone(), restaurant_admin_label()
--               admin_roster:
--                 sql       admin_recipients(), admin_for_tuid(), t_admin_link(), t_admin_profile(), t_order_card_destinations(),
--                           t_admin_restaurants()
--               admin_recipients:
--                 python    ordelo/admin_roster.py: whatsapp_phones() (P2)
--               admin_for_tuid:
--                 sql       t_order_admin_phone() (restaurant_admin/restaurant_order_decision.sql)
--               t_admin_link:
--                 python    channels/telegram/admin_links.py: link()
--               t_admin_profile:
--                 python    channels/telegram/admin_links.py: profile()
--               admin_set_channels:
--                 python    channels/telegram/admin_links.py: set_channels(); restaurant-frontend sys-admin admins route
--               admin_unlink_telegram:
--                 python    channels/telegram/admin_links.py: unlink()
--               admin_roster_status:
--                 python    ordelo/admin_roster.py: status()
-- PYTHON MODEL  channels/telegram/admin_links.py (AdminLink, AdminProfile outcome dataclasses)
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated; called with client_ordelo_service only.
--               restaurant_admin has RLS on and no policies; admin_roster is security_invoker.
-- TESTS         tests/sql/test_admin_roster_sql.py
--               tests/sql/test_admin_roster_regression_sql.py
--               tests/sql/test_admin_onboarding_script_sql.py
-- GOTCHAS       An admins[] entry that admin_phone_digits() rejects is NOT on the roster (and so gets no Telegram); the
--                 migration's PRE-CHECK 1 lists them. WhatsApp keeps reading the raw list until P2.
--               A phone shared on two restaurants has ONE record (D3): linking it links every restaurant it is on.
--               Unlinking or removing a phone from every list is the off switch; there is no "delete the record" function.
-- SEE ALSO      telegram/t_invites.sql
--               telegram/t_order_alerts.sql
--               restaurant_admin/restaurant_order_decision.sql
--               telegram/t_admin_pauses.sql
--               test_support/test_admin_onboarding.sql
--               plans/restaurant-admin-roster-onboarding-plan.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function admin_phone_digits(p_phone text) -> text
--   Digits only ('+44 7700 900123' -> '447700900123'); NULL when the result is not 8-15 digits.
--   The one phone rule for the roster: restaurant_master.admins entries and shared Telegram contacts both pass through it.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_phone_digits (p_phone text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        CASE WHEN regexp_replace(coalesce(p_phone, ''), '\D', '', 'g') ~ '^[0-9]{8,15}$' THEN
            regexp_replace(p_phone, '\D', '', 'g')
        END
$$;

-- ---------------------------------------------------------------------------------------------
-- table restaurant_admin: the admin record (CONTEXT.md). One row per phone, shared by every restaurant the phone is on.
-- Confers NO authority: membership is restaurant_master.admins (D3). Created by t_admin_link() only (D4, D13).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.restaurant_admin (
    phone text NOT NULL,                                       -- admin_phone_digits() form
    channels text[] NOT NULL DEFAULT ARRAY['whatsapp']::text[], -- where messages go (D6)
    channels_set_by text,                                      -- 'link' | 'telegram:<tuid>' | 'sys-admin' | 'operator'
    tuid bigint,                                               -- Telegram user id: authorises (D14, D25)
    tcid bigint,                                               -- Telegram chat id: addresses (private chat)
    t_username text,                                           -- display only, can change
    t_first_name text,                                         -- the "by X" label on cards and receipts
    t_linked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT restaurant_admin_pkey PRIMARY KEY (phone),
    CONSTRAINT restaurant_admin_phone_digits CHECK (phone ~ '^[0-9]{8,15}$'),
    CONSTRAINT restaurant_admin_channels_check CHECK (cardinality(channels) >= 1
        AND channels <@ ARRAY['whatsapp', 'telegram']::text[]),
    CONSTRAINT restaurant_admin_link_complete CHECK ((tuid IS NULL) = (tcid IS NULL)),
    CONSTRAINT restaurant_admin_telegram_needs_link CHECK (NOT ('telegram' = ANY (channels)) OR tuid IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS restaurant_admin_tuid_uidx ON public.restaurant_admin (tuid) WHERE tuid IS NOT NULL;
ALTER TABLE public.restaurant_admin ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.restaurant_admin FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- view admin_roster: one row per (restaurant, phone) on a restaurant's admin list, with that phone's admin record.
--   ord keeps the list order (WhatsApp sends go out in admins[] order today; P2 must not reorder them).
--   An admins[] entry that admin_phone_digits() rejects is NOT on the roster (PRE-CHECK 1 of the migration lists them).
--   channels: the record's, or {whatsapp} when there is no record (D6).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.admin_roster WITH (security_invoker = TRUE) AS
SELECT DISTINCT ON (rm.rest_ref, p.phone)
    rm.rest_ref,
    rm.rest_name,
    p.phone,
    a.ord,
    coalesce(ra.channels, ARRAY['whatsapp']::text[]) AS channels,
    ra.tuid,
    ra.tcid,
    ra.t_username,
    ra.t_first_name,
    ra.t_linked_at
FROM
    public.restaurant_master rm
    CROSS JOIN LATERAL unnest(coalesce(rm.admins, '{}'::text[])) WITH ORDINALITY AS a (raw, ord)
    CROSS JOIN LATERAL (SELECT public.admin_phone_digits (a.raw) AS phone) p
    LEFT JOIN public.restaurant_admin ra ON ra.phone = p.phone
WHERE
    p.phone IS NOT NULL
ORDER BY
    rm.rest_ref,
    p.phone,
    a.ord;
REVOKE ALL ON TABLE public.admin_roster FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function admin_recipients(p_rest_ref text, p_channel text) -> TABLE(phone, tcid, tuid, label)
--   Who gets a NEW restaurant-facing message for this restaurant on this channel ('whatsapp' | 'telegram'):
--   on the list, channel in channels, not paused (D9, any channel), and for Telegram linked. Ordered as admins[].
--   WhatsApp callers: ordelo/admin_roster.py whatsapp_phones() (P2). Telegram: t_alert_destinations() after P3.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_recipients (p_rest_ref text, p_channel text)
    RETURNS TABLE (
        phone text,
        tcid bigint,
        tuid bigint,
        label text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        r.phone,
        r.tcid,
        r.tuid,
        coalesce(r.t_first_name, '…' || RIGHT (r.phone, 4))
    FROM
        public.admin_roster r
    WHERE
        r.rest_ref = p_rest_ref
        AND p_channel = ANY (r.channels)
        AND (p_channel <> 'telegram' OR r.tcid IS NOT NULL)
        AND NOT public.is_paused ('rest_admin', r.phone, p_rest_ref)
    ORDER BY
        r.ord
$$;
REVOKE ALL ON FUNCTION public.admin_recipients (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function admin_for_tuid(p_tuid bigint, p_rest_ref text) -> text
--   The admin phone of this Telegram user for this restaurant (linked record AND phone on that restaurant's list), else NULL.
--   Channel-independent (D6): a WhatsApp-only admin who is linked may still act from Telegram.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_for_tuid (p_tuid bigint, p_rest_ref text)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT r.phone FROM public.admin_roster r WHERE r.tuid = p_tuid AND r.rest_ref = p_rest_ref LIMIT 1
$$;
REVOKE ALL ON FUNCTION public.admin_for_tuid (bigint, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_admin_link(p_tuid, p_tcid, p_phone, p_username, p_first_name) -> jsonb
--   The admin link (CONTEXT.md). Callers MUST have checked contact.user_id == from_user.id (D2); never typed text.
--   RESULT VOCABULARY
--     linked          first link for this phone: record created/filled, channels := {telegram} (D6)
--     relinked        another Telegram account proved this phone: link moved, channels kept; previous_tuid/username returned (D8)
--     already_linked  same phone, same account: tcid / username / first name refreshed, channels kept
--     not_on_roster   the phone is on no restaurant's admin list: nothing written (D5)
--     tuid_taken      this Telegram account is linked to a DIFFERENT phone: refused (D8)
--     bad_phone       not 8-15 digits, or missing ids
--   Every linked/relinked/already_linked result carries phone, channels and restaurants:[{rest_ref, rest_name}].
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_phone text := admin_phone_digits (p_phone);
    v_row restaurant_admin%ROWTYPE;
    v_other text;
    v_result text;
    v_prev_tuid bigint;
    v_prev_username text;
BEGIN
    IF v_phone IS NULL OR p_tuid IS NULL OR p_tcid IS NULL THEN
        RETURN jsonb_build_object('result', 'bad_phone');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM admin_roster r WHERE r.phone = v_phone) THEN
        RETURN jsonb_build_object('result', 'not_on_roster');
    END IF;
    SELECT phone INTO v_other FROM restaurant_admin WHERE tuid = p_tuid AND phone <> v_phone;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'tuid_taken', 'phone_last4', RIGHT (v_other, 4));
    END IF;
    INSERT INTO restaurant_admin (phone) VALUES (v_phone) ON CONFLICT (phone) DO NOTHING;
    SELECT * INTO v_row FROM restaurant_admin WHERE phone = v_phone FOR UPDATE;
    IF v_row.tuid IS NULL THEN
        UPDATE restaurant_admin
        SET tuid = p_tuid, tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, t_linked_at = now(),
            channels = ARRAY['telegram']::text[], channels_set_by = 'link', updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'linked';
    ELSIF v_row.tuid = p_tuid THEN
        UPDATE restaurant_admin
        SET tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'already_linked';
    ELSE
        v_prev_tuid := v_row.tuid;
        v_prev_username := v_row.t_username;
        UPDATE restaurant_admin
        SET tuid = p_tuid, tcid = p_tcid, t_username = p_username, t_first_name = p_first_name, t_linked_at = now(),
            updated_at = now()
        WHERE phone = v_phone
        RETURNING * INTO v_row;
        v_result := 'relinked';
    END IF;
    RETURN jsonb_build_object(
        'result', v_result, 'phone', v_row.phone, 'channels', to_jsonb(v_row.channels),
        'restaurants', (SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name)
                                                  ORDER BY r.rest_ref), '[]'::jsonb)
                          FROM admin_roster r WHERE r.phone = v_phone),
        'previous_tuid', v_prev_tuid, 'previous_username', v_prev_username);
EXCEPTION
    WHEN unique_violation THEN
        -- restaurant_admin_tuid_uidx: the same account was linked to another phone by a concurrent call.
        RETURN jsonb_build_object('result', 'tuid_taken');
END;
$$;
REVOKE ALL ON FUNCTION public.t_admin_link (bigint, bigint, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_admin_profile(p_tuid bigint) -> jsonb
--   {result: ok | not_linked | not_on_roster, phone, channels, t_first_name, restaurants:[{rest_ref, rest_name}]}
--   not_on_roster: linked record whose phone is on no list any more (removed by an operator): no authority, no messages.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_admin_profile (p_tuid bigint)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        CASE WHEN ra.phone IS NULL THEN
            jsonb_build_object('result', 'not_linked')
        ELSE
            jsonb_build_object(
                'result', CASE WHEN EXISTS (SELECT 1 FROM admin_roster r WHERE r.phone = ra.phone) THEN 'ok' ELSE 'not_on_roster' END,
                'phone', ra.phone, 'channels', to_jsonb(ra.channels), 't_first_name', ra.t_first_name,
                'restaurants', (SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', r.rest_ref, 'rest_name', r.rest_name)
                                                          ORDER BY r.rest_ref), '[]'::jsonb)
                                  FROM admin_roster r WHERE r.phone = ra.phone))
        END
    FROM (SELECT 1) one
    LEFT JOIN restaurant_admin ra ON ra.tuid = p_tuid
$$;
REVOKE ALL ON FUNCTION public.t_admin_profile (bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function admin_set_channels(p_phone text, p_channels text[], p_by text) -> jsonb
--   {result: ok | not_found | bad_channels | not_linked, channels}
--   not_found: no admin record (an unlinked admin is WhatsApp-only and has nothing to change).
--   not_linked: Telegram asked for but the record has no Telegram link (the CHECK would refuse it).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_set_channels (p_phone text, p_channels text[], p_by text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_phone text := admin_phone_digits (p_phone);
    v_channels text[] := ARRAY (SELECT DISTINCT c FROM unnest(coalesce(p_channels, '{}'::text[])) c ORDER BY c);
    v_row restaurant_admin%ROWTYPE;
BEGIN
    IF cardinality(v_channels) = 0 OR NOT v_channels <@ ARRAY['whatsapp', 'telegram']::text[] THEN
        RETURN jsonb_build_object('result', 'bad_channels');
    END IF;
    SELECT * INTO v_row FROM restaurant_admin WHERE phone = v_phone FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    IF 'telegram' = ANY (v_channels) AND v_row.tuid IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked', 'channels', to_jsonb(v_row.channels));
    END IF;
    UPDATE restaurant_admin SET channels = v_channels, channels_set_by = p_by, updated_at = now()
    WHERE phone = v_phone RETURNING * INTO v_row;
    RETURN jsonb_build_object('result', 'ok', 'channels', to_jsonb(v_row.channels));
END;
$$;
REVOKE ALL ON FUNCTION public.admin_set_channels (text, text[], text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function admin_unlink_telegram(p_phone text, p_by text) -> jsonb
--   Clear the Telegram link and go back to WhatsApp only. {result: ok | not_found | not_linked}. The person can link
--   again by sharing their number. Removing a phone from every admins[] list stays the real off switch (D3).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.admin_unlink_telegram (p_phone text, p_by text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_row restaurant_admin%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM restaurant_admin WHERE phone = admin_phone_digits (p_phone) FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    ELSIF v_row.tuid IS NULL THEN
        RETURN jsonb_build_object('result', 'not_linked');
    END IF;
    UPDATE restaurant_admin
    SET tuid = NULL, tcid = NULL, t_username = NULL, t_first_name = NULL, t_linked_at = NULL,
        channels = ARRAY['whatsapp']::text[], channels_set_by = p_by, updated_at = now()
    WHERE phone = v_row.phone;
    RETURN jsonb_build_object('result', 'ok');
END;
$$;
REVOKE ALL ON FUNCTION public.admin_unlink_telegram (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function admin_roster_status(p_rest_ref text) -> jsonb
--   The sys-admin page's view of one restaurant's list, in list order, INCLUDING entries the roster rejects (valid=false)
--   so the operator can fix them: [{raw, phone, valid, linked, t_username, t_first_name, t_linked_at, channels, paused,
--   legacy_invite}]. legacy_invite (TRANSITION, removed in P3): a claimed t_invites row exists for this phone and restaurant.
-- ---------------------------------------------------------------------------------------------
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
                                      WHERE i.rest_ref = rm.rest_ref AND i.status = 'claimed'
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

INSERT INTO ordelo_config (config_key, config_value, description)
    VALUES ('TGRAM_REST_ADMIN_BOT_USERNAME', 'OrdeloRestaurantBot', 'Restaurant-admin Telegram bot')
ON CONFLICT (config_key) DO NOTHING;

-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- and any SQL client show them.
COMMENT ON FUNCTION public.admin_phone_digits (p_phone text) IS 'Digits only; NULL unless 8-15 digits. The one phone rule of the admin roster.';

COMMENT ON TABLE public.restaurant_admin IS 'The admin record: one row per phone with the chosen channels and the Telegram link. Confers no authority; restaurant_master.admins does.';

COMMENT ON VIEW public.admin_roster IS 'One row per (restaurant, phone) on a restaurant admin list, with that phone''s admin record (channels default to whatsapp).';

COMMENT ON FUNCTION public.admin_recipients (p_rest_ref text, p_channel text) IS 'Who gets a NEW message for this restaurant on this channel: on the list, channel chosen, not paused, (telegram) linked.';

COMMENT ON FUNCTION public.admin_for_tuid (p_tuid bigint, p_rest_ref text) IS 'The admin phone of this Telegram user for this restaurant (linked and on its list), else NULL.';

COMMENT ON FUNCTION public.t_admin_link (p_tuid bigint, p_tcid bigint, p_phone text, p_username text, p_first_name text) IS 'Link a Telegram account to an admin phone (shared by the sender, never typed): linked, relinked, already_linked, not_on_roster, tuid_taken, bad_phone.';

COMMENT ON FUNCTION public.t_admin_profile (p_tuid bigint) IS 'Who this Telegram account is as an admin: phone, channels and restaurants; read-only.';

COMMENT ON FUNCTION public.admin_set_channels (p_phone text, p_channels text[], p_by text) IS 'Change where an admin''s messages go (whatsapp, telegram or both); telegram needs a link.';

COMMENT ON FUNCTION public.admin_unlink_telegram (p_phone text, p_by text) IS 'Clear the Telegram link of an admin and return them to WhatsApp only.';

COMMENT ON FUNCTION public.admin_roster_status (p_rest_ref text) IS 'One restaurant''s admin list with link and channel state, including entries the roster rejects, for the sys-admin page.';
