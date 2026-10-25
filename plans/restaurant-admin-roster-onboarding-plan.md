# Restaurant-admin roster and phone-verified onboarding (WhatsApp + Telegram)

Status: **plan, not started** (24 Oct 2026). The SQL in sections 4.1 and 4.2 was loaded into a throwaway local
Postgres 16 (with `tests/sql/minimal_schema.sql`, `availability/pauses.sql`, `telegram/t_invites.sql`) and walked through
every link result, channel change, pause, removal, a phone on two restaurants and the invite transition: it compiles and
behaves as described. It has not been run against any shared database. Written from a grilling session with the owner (decisions D1-D13 below) against
OrdeloAgent `dev` at `d486b43`, restaurant-frontend `dfac2fc`. Nothing in this plan has been applied to any database.

Glossary terms used here are defined in `CONTEXT.md` (Admin roster, Admin record, Admin link, Admin channels, Pause).
Architecture vocabulary (module, interface, seam, adapter, depth) as in the codebase-design skill.

**Owner rules for whoever implements this**

1. **Never run SQL against the shared database.** Prepare files only. The owner applies every migration step himself.
2. **WhatsApp must keep working, byte for byte.** An admin who has not linked Telegram keeps receiving exactly today's
   WhatsApp messages (same text, same buttons, same callback JSON, same order of recipients). Every phase has a regression
   gate for this (section 9).
3. **Live testing uses `ordelo_datamodels/test_support/test_restaurant_notices.sql`** wherever it covers the feature. A new
   test SQL exists only for what it cannot cover (linking, channels, roster membership): `test_admin_onboarding.sql`.
4. Follow `CLAUDE.md` / `agents.md`: RPC owns the logic, one Python wrapper per domain, the 13-section SQL header,
   cross-references both ways, `python scripts/datamodels/build_guide.py` after any SQL header change, `drift_check.py`
   after the owner applies SQL, `asyncio.to_thread` around every Supabase call.

---

## 1. What changes for people

| Who | Today | After |
|---|---|---|
| Operator | Adds the phone in the sys-admin page (WhatsApp), then hand-writes `INSERT INTO t_invites`, copies a link from `t_invites_shareable`, sends it privately, checks who claimed it | Adds the phone in the sys-admin page. Sends everyone the same link `t.me/OrdeloRestaurantBot?start=admin`. The page shows who has linked and lets the operator change channels or unlink |
| Restaurant admin, not on Telegram | Gets everything on WhatsApp | Unchanged |
| Restaurant admin who links Telegram | Opens a private invite, taps Yes; then gets **both** WhatsApp and Telegram | Opens the bot, taps **Share my phone number**; the number must be on a restaurant's admin list. From then on alerts come **on Telegram only** (WhatsApp stops), for every restaurant they are on |
| Someone not on any list | (could claim a forwarded invite) | Refused; ops gets one line |
| `/off` on the restaurant bot | Pauses Telegram alerts only | Pauses the admin on all their channels |

## 2. Decisions (grilling session, 24 Oct 2026)

| # | Decision |
|---|---|
| D1 | Build the roster (candidate 1) and the contact-share link (candidate 2) together. |
| D2 | Telegram admins prove their phone with Telegram's contact button, accepted only when `contact.user_id == from_user.id`, exactly like the rider bot (D39). Reverses ADR 0011 Amendment 1 (private invites). |
| D3 | `restaurant_master.admins` stays the **authority** on who is an admin of which restaurant (edited in the sys-admin page). A person may be on several restaurants' lists; they are an admin while on at least one. |
| D4 | New table `restaurant_admin`: **one row per phone** (the admin record): Telegram link and channels. No authority by itself. Created when the person first links. |
| D5 | A shared number on no restaurant's list is refused (`not_on_roster`) and ops is told. Only operators enrol admins. |
| D6 | Channels: `whatsapp`, `telegram` or both, never none, on the admin record. No record = WhatsApp only. **Linking sets channels to Telegram only** (owner, 24 Oct: "once the admin registers on Telegram he stops getting WhatsApp"). The operator (sys-admin page) and the admin (`/channels`) can change it. Channels decide where messages go, never what an admin may do. |
| D7 | Clean cut-over: claimed invites are **not** migrated; invites are retired. |
| D8 | Same phone + new Telegram account -> link moves (`relinked`, ops told); account already linked to another phone -> `tuid_taken`; same account -> `already_linked` (refresh). Rider rules, D42. |
| D9 | A pause covers the admin on **all** channels; the last-admin guard is unchanged in code (it already counts unpaused admins on the list). ADR 0013 amendment. |
| D10 | Operator surface: the sys-admin restaurants page (status, channels, unlink, copy the fixed bot link). An automatic WhatsApp welcome is later work. |
| D11 | Roster RPCs in `ordelo_datamodels/restaurant_admin/admin_roster.sql`; Python `ordelo/admin_roster.py` (channel-neutral) and `channels/telegram/admin_links.py` (mirrors `rider_links.py`). Existing `t_*` functions keep names and signatures; only bodies change. |
| D12 | Phased: link early, WhatsApp honours channels, then cut-over (section 3). |
| D13 | Defaults accepted with the summary: no `phone_verified` column (every record is created by a verified share); one digits-only phone rule shared by both sides; operator "Unlink Telegram"; ops alerts via the existing WhatsApp ops logger; group chats, Telegram dashboard login and restaurant-agents leftovers out of scope. |

## 3. Phases

The owner agreed "link early, switch later" (Q12). Because of D6 (linking stops WhatsApp) the WhatsApp change is now
the second phase and the invite cut-over the third: the cut-over then only deletes code paths nobody needs.

| Phase | Ships | SQL the owner applies | Behaviour after it |
|---|---|---|---|
| **P1 Roster + link** | `admin_roster.sql`; `t_*` bodies read records **or** claimed invites; contact-share `/start`, `/channels`, `/whoami`; sys-admin page; new harness | `migrations/admin_roster_p1.sql` (steps inside) | Admins can link by sharing their number. Invite-linked admins keep Telegram. WhatsApp completely unchanged (linked admins temporarily get both) |
| **P2 WhatsApp honours channels** | Every WhatsApp admin send goes through the restaurant notifier and `admin_roster.whatsapp_phones()`; two WhatsApp-only messages get Telegram twins; pause text | none (code only) | Linked admins stop getting WhatsApp. Paused admins get nothing on either channel. Unlinked admins: identical WhatsApp |
| **P3 Cut-over** (date chosen by owner, after evening service) | Invite branches removed from `t_*` bodies; invite handlers, `invites.py`, keyboards and callbacks deleted | `migrations/admin_roster_p3_cutover.sql` | Only admin records reach Telegram. Unlinked admins are WhatsApp-only |

Each phase is its own PR. P2 must not merge until P1 has run live for at least one service with a linked admin.

---

## 4. Database (P1): `ordelo_datamodels/restaurant_admin/admin_roster.sql` (new file)

One file, standard header (13 sections). Objects, in file order (dependency order matters: SQL-language functions are
checked when created):

| Object | Kind | Purpose |
|---|---|---|
| `admin_phone_digits(text) -> text` | fn, IMMUTABLE | digits only; NULL unless 8-15 digits. The one phone rule (D13) |
| `restaurant_admin` | table | the admin record (D4) |
| `admin_roster` | view (security_invoker) | every (restaurant, phone) on an admin list + that phone's record |
| `admin_recipients(p_rest_ref, p_channel)` | fn | who gets a NEW message on this channel: on the list, channel set, not paused, (Telegram) linked; list order kept |
| `admin_for_tuid(p_tuid, p_rest_ref) -> text` | fn | the phone of this Telegram user if they are an admin of this restaurant, else NULL |
| `t_admin_link(p_tuid, p_tcid, p_phone, p_username, p_first_name)` | fn | the link (D2, D5, D6, D8) |
| `t_admin_profile(p_tuid)` | fn | who this Telegram account is as an admin (read-only) |
| `admin_set_channels(p_phone, p_channels, p_by)` | fn | change channels (D6) |
| `admin_unlink_telegram(p_phone, p_by)` | fn | operator unlink (D13) |
| `admin_roster_status(p_rest_ref)` | fn | one restaurant's list for the sys-admin page |
| `ordelo_config` row `TGRAM_REST_ADMIN_BOT_USERNAME` | data | moved here from `t_invites.sql` (`ON CONFLICT DO NOTHING`), used by the page for the fixed link |

Names differ slightly from the grilling sketch (`admin_for` -> `admin_for_tuid`, `admin_link` -> `t_admin_link`,
`admin_profile` -> `t_admin_profile`): the `t_` prefix marks functions keyed by Telegram ids, as `t_rider_link` is.

### 4.1 SQL (copy, then add the 13-section header and `COMMENT ON` lines)

```sql
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
```

Notes for the implementer:

- `admin_roster_status` references `t_invites`, so in `tests/sql/conftest.py` `admin_roster.sql` must come **after**
  `t_invites.sql` and `pauses.sql`, and **before** `t_order_alerts.sql` (which will call `admin_roster`):
  ```diff
   MIGRATION_FILES = [
       "t_inbox.sql",
       "t_sent_messages.sql",
       "t_invites.sql",
  -    "restaurant_order_decision.sql",
       # pauses.sql (rider bot R1) comes before t_order_alerts.sql since R6: ...
       "pauses.sql",
  +    # Admin roster (plans/restaurant-admin-roster-onboarding-plan.md): before every t_* function that reads it.
  +    "admin_roster.sql",
  +    "restaurant_order_decision.sql",
       "t_order_alerts.sql",
  ```
  (`restaurant_order_decision.sql` moves below `admin_roster.sql` because `t_order_admin_phone` and
  `restaurant_admin_label` now read the roster. Check `pauses.sql` does not need `restaurant_order_decision.sql` first;
  today it reads only `restaurant_master`.)
- `tests/sql/minimal_schema.sql` already has `restaurant_master(rest_ref, rest_name, admins text[])` and an `ordelo_config`
  table is needed for the INSERT (check it exists there; `t_invites.sql` already inserts into it, so it does).
- `guide_content.json`: add the objects to the `restaurant_admin` capability; then `python scripts/datamodels/build_guide.py`.
- `core/restaurant_master.sql`: change the `admins` column comment and the HOW IT FITS line to "authoritative admin list
  (D3); Telegram link and channels per phone in restaurant_admin/admin_roster.sql". `COMMENT ON COLUMN` on live is an owner
  step (listed in the migration).

### 4.2 Existing `t_*` functions: new bodies (P1, with a TRANSITION branch that P3 deletes)

Signatures unchanged (D11), so `channels/telegram/rest_admin/order_cards/*`, `receipts`, `notices.py`, `admin_pauses.py`
and their tests do not move. Every invite branch is marked `-- TRANSITION (P3 removes)` so P3 is a pure deletion.

Rule for the transition: **a phone that has an admin record is governed only by the record**; claimed invites count only
for phones with no record. So once someone links, their old invite stops mattering.

**`telegram/t_order_alerts.sql` `t_order_card_destinations(p_bot_key, p_rest_ref)`** (who may see and tap, and where
copies are cleaned up; channel-independent):

```sql
    SELECT DISTINCT ON (x.tcid) x.tcid, x.tuid, x.phone, x.label
    FROM (
        SELECT r.tcid, r.tuid, r.phone, r.t_first_name AS label, 1 AS pri, r.t_linked_at AS at
        FROM public.admin_roster r
        WHERE r.rest_ref = p_rest_ref AND r.tcid IS NOT NULL
        UNION ALL
        -- TRANSITION (P3 removes): claimed invites of listed phones that have no admin record yet
        SELECT i.telegram_chat_id, i.telegram_user_id, r.phone, i.telegram_first_name, 2, i.claimed_at
        FROM public.t_invites i
        JOIN public.admin_roster r ON r.rest_ref = i.rest_ref AND r.phone = public.admin_phone_digits (i.phone_number)
        WHERE i.bot_key = p_bot_key AND i.rest_ref = p_rest_ref AND i.status = 'claimed'
          AND i.telegram_chat_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM public.restaurant_admin ra WHERE ra.phone = r.phone)
    ) x
    ORDER BY x.tcid, x.pri, x.at DESC NULLS LAST
```

**`t_alert_destinations(p_bot_key, p_rest_ref)`** (where NEW cards, receipts and notices go):

```sql
    SELECT d.tcid, d.tuid, d.phone, d.label
    FROM public.t_order_card_destinations (p_bot_key, p_rest_ref) d
    LEFT JOIN public.restaurant_admin ra ON ra.phone = d.phone
    WHERE NOT public.is_paused ('rest_admin', d.phone, p_rest_ref)
      AND (ra.phone IS NULL            -- TRANSITION (P3 removes): invite-only admins keep Telegram as today
           OR 'telegram' = ANY (ra.channels))
```

After P3 both collapse to the roster:
`t_order_card_destinations` = `SELECT tcid, tuid, phone, t_first_name FROM admin_roster WHERE rest_ref = p_rest_ref AND tcid IS NOT NULL`
(DISTINCT ON tcid) and `t_alert_destinations` = `SELECT tcid, tuid, phone, label FROM admin_recipients(p_rest_ref, 'telegram')`.
`p_bot_key` stays in the signature (callers pass it); the record belongs to the `rest_admin` bot.

**`restaurant_admin/restaurant_order_decision.sql`**

`t_order_admin_phone(p_bot_key, p_tuid, p_rest_ref)`:

```sql
    SELECT coalesce(
        public.admin_for_tuid (p_tuid, p_rest_ref),
        -- TRANSITION (P3 removes): invite-linked admins whose phone has no admin record
        (SELECT r.phone
           FROM public.t_invites i
           JOIN public.admin_roster r ON r.rest_ref = i.rest_ref AND r.phone = public.admin_phone_digits (i.phone_number)
          WHERE i.bot_key = p_bot_key AND i.telegram_user_id = p_tuid AND i.rest_ref = p_rest_ref AND i.status = 'claimed'
            AND NOT EXISTS (SELECT 1 FROM public.restaurant_admin ra WHERE ra.phone = r.phone)
          ORDER BY i.claimed_at DESC NULLS LAST
          LIMIT 1))
```

`restaurant_admin_label(p_phone)`:

```sql
    SELECT coalesce(
        (SELECT ra.t_first_name FROM public.restaurant_admin ra
          WHERE ra.phone = public.admin_phone_digits (p_phone) AND ra.t_first_name IS NOT NULL),
        -- TRANSITION (P3 removes)
        (SELECT i.telegram_first_name FROM public.t_invites i
          WHERE i.phone_number = p_phone AND i.status = 'claimed' AND i.telegram_first_name IS NOT NULL
          ORDER BY i.claimed_at DESC LIMIT 1),
        CASE WHEN coalesce(p_phone, '') = '' THEN NULL ELSE '…' || RIGHT (p_phone, 4) END)
```

Update the header (`REQUIRES` gains `restaurant_admin/admin_roster.sql`; `HOW IT FITS`, `CALLED BY`) and
`utils_common/order_management/restaurant_decision.py` docstring line 15 ("the 'by X' label comes from t_invites" ->
"from restaurant_admin (admin_roster.sql)").

**`telegram/t_admin_pauses.sql`**: `t_admin_pause`, `t_admin_resume`, `t_admin_pause_status` each contain the same
subquery over `t_invites` (lines 76-88, 123-135, 166-178). Replace it, in all three, with a new helper in the same file:

```sql
-- function t_admin_restaurants(p_bot_key text, p_tuid bigint) -> TABLE(rest_ref text, rest_name text, phone text)
--   The restaurants this Telegram user is an admin of, with their admin phone (roster), for /off, /on and the status.
CREATE OR REPLACE FUNCTION public.t_admin_restaurants (p_bot_key text, p_tuid bigint)
    RETURNS TABLE (rest_ref text, rest_name text, phone text)
    LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT r.rest_ref::text, r.rest_name, r.phone FROM public.admin_roster r WHERE r.tuid = p_tuid
    UNION
    -- TRANSITION (P3 removes)
    SELECT i.rest_ref::text, rm.rest_name, public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref)
      FROM public.t_invites i JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
     WHERE i.bot_key = p_bot_key AND i.telegram_user_id = p_tuid AND i.status = 'claimed'
       AND public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) IS NOT NULL
$$;
REVOKE ALL ON FUNCTION public.t_admin_restaurants (text, bigint) FROM PUBLIC, anon, authenticated;
```

and in each of the three functions:

```diff
-    FROM (
-        SELECT DISTINCT
-            i.rest_ref,
-            public.t_order_admin_phone (p_bot_key, p_tuid, i.rest_ref) AS phone
-        FROM
-            public.t_invites i
-        WHERE
-            i.bot_key = p_bot_key
-            AND i.telegram_user_id = p_tuid
-            AND i.status = 'claimed') x
-    JOIN public.restaurant_master rm ON rm.rest_ref = x.rest_ref
-WHERE
-    x.phone IS NOT NULL
+    FROM public.t_admin_restaurants (p_bot_key, p_tuid) x
```

(select `x.rest_ref, x.rest_name, x.phone` instead of `rm.rest_name`). `t_admin_pause_chats` is unchanged (it reads
`t_order_card_destinations`). `pause_start`'s last-admin guard in `availability/pauses.sql` is unchanged (D9): it already
counts unpaused phones on `restaurant_master.admins`; only its header comment changes ("WhatsApp alerts are not affected"
becomes "a pause applies on every channel from P2").

**`restaurant_admin/restaurant_ready_adjust_notices.sql`**: no body change (`t_notice_targets` and `t_receipt_snapshot`
read `t_alert_destinations`, the stale-copy sweep reads `t_order_card_destinations`). Re-apply it only if the guide/drift
check asks (header `REQUIRES`).

**`telegram/t_invites.sql`**: P1 no body change. Header: "Being retired (plans/restaurant-admin-roster-onboarding-plan.md):
no new invites; claims are no longer offered by the bot from P1; dropped in P3". Move the `ordelo_config` INSERT
comment to point at `admin_roster.sql`.

### 4.3 `ordelo_datamodels/migrations/admin_roster_p1.sql` (new; the owner applies it)

Header as `rider_telegram_r5_r6.sql`. Content:

```text
HOW TO APPLY (Supabase SQL editor, one block at a time; no BEGIN/COMMIT):
  STEP 0  PRE-CHECKs below; fix PRE-CHECK 1 rows in the sys-admin page first (they would drop off the roster).
  STEP 1  Apply whole files, in this order:
            ordelo_datamodels/restaurant_admin/admin_roster.sql
            ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql   (t_order_admin_phone, restaurant_admin_label)
            ordelo_datamodels/telegram/t_order_alerts.sql                      (re-schedules job_t_order_alerts unchanged)
            ordelo_datamodels/telegram/t_admin_pauses.sql                      (t_admin_restaurants, new)
  STEP 2  VERIFY below.
  STEP 3  Deploy the P1 code (OrdeloAgent + restaurant-frontend), then python scripts/datamodels/drift_check.py
  STEP 4  Re-publish the restaurant bot menu: notebooks/telegram/tgram_setup_bot.py with BOT_KEY = 'rest_admin'
          (/start text changed, /channels added).
  STEP 5  OPTIONAL (owner decision): stop pending invites from being claimed by an old message:
            UPDATE public.t_invites SET status = 'revoked' WHERE status = 'pending' RETURNING invite_code, rest_ref;
  STEP 6  Live test: test_support/test_admin_onboarding.sql, then test_support/test_restaurant_notices.sql (section 9).
  Order: STEP 1 before the deploy (the new code calls t_admin_link / t_admin_profile; old code ignores the new objects,
  and the new t_* bodies give exactly today's destinations while no admin record exists: proven by VERIFY 2).
ROLLBACK: redeploy the previous code; re-apply the previous t_order_alerts.sql, restaurant_order_decision.sql and
  t_admin_pauses.sql from git (git show d486b43:<path>). The new table and functions are additive; leave them.
```

PRE-CHECKs (read-only):

```sql
-- PRE-CHECK 1: admins[] entries the roster would reject (must be 0 rows, or fix them first)
SELECT rm.rest_ref, a AS entry FROM public.restaurant_master rm, unnest(coalesce(rm.admins, '{}')) a
 WHERE regexp_replace(a, '\D', '', 'g') !~ '^[0-9]{8,15}$';
-- PRE-CHECK 2: today's Telegram destinations per restaurant (compare with VERIFY 2)
SELECT rest_ref, (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', rest_ref)) AS destinations
  FROM public.restaurant_master ORDER BY 1;
-- PRE-CHECK 3: phones on more than one restaurant (expected: your team's numbers; D3 allows it)
SELECT regexp_replace(a, '\D', '', 'g') AS phone, array_agg(rest_ref ORDER BY rest_ref) AS restaurants
  FROM public.restaurant_master, unnest(coalesce(admins, '{}')) a GROUP BY 1 HAVING count(*) > 1;
```

VERIFY:

```sql
SELECT
  (SELECT count(*) FROM pg_proc WHERE proname IN ('admin_phone_digits','admin_recipients','admin_for_tuid','t_admin_link',
      't_admin_profile','admin_set_channels','admin_unlink_telegram','admin_roster_status','t_admin_restaurants')) AS functions, -- 9
  (SELECT count(*) FROM public.restaurant_admin) AS admin_records,                                                              -- 0
  (SELECT prosrc LIKE '%admin_roster%' FROM pg_proc WHERE proname = 't_order_card_destinations') AS destinations_use_roster;    -- true
-- VERIFY 2: same numbers as PRE-CHECK 2 (no admin record exists yet, so nothing may change)
SELECT rest_ref, (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', rest_ref)) AS destinations
  FROM public.restaurant_master ORDER BY 1;
```

---

## 5. OrdeloAgent Python (P1)

### 5.1 `ordelo/admin_roster.py` (new, channel-neutral)

```python
"""
Admin roster: who a restaurant's admins are and where each one hears from Ordelo (CONTEXT.md: Admin roster, Admin channels).
    . Thin async wrapper over SQL functions. The rules live in the database (CLAUDE.md, RPC pattern).
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/admin_roster.sql (keep in sync)
    . Python function -> RPC it calls:
        recipients       -> admin_recipients(p_rest_ref, p_channel)
        whatsapp_phones  -> admin_recipients(p_rest_ref, 'whatsapp'); FAIL-OPEN to today's admins list (owner rule 2)
        set_channels     -> admin_set_channels(p_phone, p_channels, p_by)
        unlink_telegram  -> admin_unlink_telegram(p_phone, p_by)
        roster_status    -> admin_roster_status(p_rest_ref)
    . Called by: utils_common/notify/restaurant_notifier.py (WhatsApp adapter, P2), watomation/routers/delivery_hooks.py
      (admin availability enquiry, P2), channels/telegram/admin_links.py (/channels)
    . Uses client_ordelo_service (service-role only RPCs); every call in asyncio.to_thread
  Classes/Functions:
    . Recipient, recipients, whatsapp_phones, set_channels, unlink_telegram, roster_status

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . admin_recipients (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_set_channels (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_unlink_telegram (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
  . admin_roster_status (function, ordelo_datamodels/restaurant_admin/admin_roster.sql): calls (name passed to a helper)
(end of database objects)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from config import client_ordelo_service, logger

Channel = Literal["whatsapp", "telegram"]
SET_CHANNELS_RESULTS = frozenset({"ok", "not_found", "bad_channels", "not_linked"})


@dataclass(frozen=True)
class Recipient:
    phone: str
    tcid: int | None
    tuid: int | None
    label: str | None


async def _rpc(name: str, args: dict) -> Any:
    resp = await asyncio.to_thread(lambda: client_ordelo_service.rpc(name, args).execute())
    return resp.data


async def recipients(rest_ref: str, channel: Channel) -> list[Recipient]:
    data = await _rpc("admin_recipients", {"p_rest_ref": rest_ref, "p_channel": channel})
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected admin_recipients response: {data!r}")
    return [Recipient(r["phone"], r.get("tcid"), r.get("tuid"), r.get("label")) for r in data]


async def _todays_admins(rest_ref: str | None, fallback: Iterable[str] | None) -> list[str]:
    if fallback is None and rest_ref:
        from ordelo_datamodels.restaurant_master_pymodel import RestaurantMaster

        fallback = await asyncio.to_thread(RestaurantMaster.get_admins_for, rest_ref) or []
    return list(dict.fromkeys(a for a in (fallback or []) if a))


async def whatsapp_phones(rest_ref: str | None, *, fallback: Iterable[str] | None = None) -> list[str]:
    """The admins of rest_ref who get WhatsApp now (list order, D6/D9). NEVER raises and never returns fewer people than
    today because of a fault: with no rest_ref or on any RPC failure it returns `fallback` (or, when None,
    restaurant_master.admins), deduped in order: exactly today's behaviour."""
    if rest_ref:
        try:
            return [r.phone for r in await recipients(rest_ref, "whatsapp")]
        except Exception:
            logger.exception(f"admin_roster: whatsapp recipients for {rest_ref} failed; using restaurant_master.admins")
    return await _todays_admins(rest_ref, fallback)
```

(`set_channels`, `unlink_telegram`, `roster_status` are one-line `_rpc` wrappers returning small frozen dataclasses with
`result`, like `rider_links.py`.)

### 5.2 `channels/telegram/admin_links.py` (new; mirrors `channels/telegram/rider_links.py`)

```python
"""
Restaurant-admin bot identity: link a Telegram account to an admin record by a verified phone (D2).
    . RPCs are DEFINED in: ordelo_datamodels/restaurant_admin/admin_roster.sql
    . Python function -> RPC it calls:
        link     -> t_admin_link(p_tuid, p_tcid, p_phone, p_username, p_first_name)
        profile  -> t_admin_profile(p_tuid)
    . Callers MUST have checked contact.user_id == from_user.id before link(); the phone is never taken from text
    . Called by: channels/telegram/rest_admin/router.py, channels/telegram/rest_admin/channels.py
    . Uses client_ordelo_service; asyncio.to_thread
  Classes/Functions:
    . AdminRestaurant, AdminLink, AdminProfile, link, profile
Database objects (...): t_admin_link, t_admin_profile (function, ordelo_datamodels/restaurant_admin/admin_roster.sql)
"""

# t_admin_link results: linked | relinked | already_linked | not_on_roster | tuid_taken | bad_phone
LINKED_RESULTS = frozenset({"linked", "relinked", "already_linked"})


@dataclass(frozen=True)
class AdminRestaurant:
    rest_ref: str
    rest_name: str


@dataclass(frozen=True)
class AdminLink:
    result: str
    phone: str | None = None
    channels: tuple[str, ...] = ()
    restaurants: tuple[AdminRestaurant, ...] = ()
    previous_tuid: int | None = None
    previous_username: str | None = None
    phone_last4: str | None = None

    @property
    def is_linked(self) -> bool:
        return self.result in LINKED_RESULTS


@dataclass(frozen=True)
class AdminProfile:
    result: str  # ok | not_linked | not_on_roster
    phone: str | None = None
    channels: tuple[str, ...] = ()
    t_first_name: str | None = None
    restaurants: tuple[AdminRestaurant, ...] = ()

    @property
    def is_admin(self) -> bool:
        return self.result == "ok"
```

`link()` / `profile()` follow `rider_links.link` / `rider_links.profile` exactly (`_checked`, `_rpc`), converting
`restaurants` lists into tuples of `AdminRestaurant`.

### 5.3 Shared ops alert: `channels/telegram/ops_alerts.py` (new)

Move `alert_ops` and `_mask` out of `channels/telegram/rider/router.py` (lines ~78-92) unchanged, so both bots use
one helper:

```diff
# channels/telegram/rider/router.py
-async def alert_ops(text: str) -> None:
-    """One line to the overwatch WhatsApp numbers (existing WALogger). Never raises: an alert must not break onboarding."""
-    ...
-def _mask(phone: str | None) -> str:
-    return f"…{phone[-4:]}" if phone else "?"
+from ..ops_alerts import alert_ops, mask as _mask
```

The `ops_alerts` fixture in `tests/channels/telegram/conftest.py` (line ~532) patches
`channels.telegram.rider.router.alert_ops`; that keeps working because the router binds the name at import. Extend the
fixture to also patch `channels.telegram.rest_admin.router.alert_ops` (same `sent` list).

### 5.4 `channels/telegram/rest_admin/router.py` (P1 diff)

Replace the invite onboarding with contact share. Key changes:

```diff
-from .. import invites
-from ..callbacks import InviteDecision
+from .. import admin_links, invites  # invites: TRANSITION (P3 removes) - legacy-link hint in /start and /whoami
+from ..callbacks import InviteDecision  # TRANSITION (P3 removes): old "Link this chat?" messages still have buttons
 from ..inbox import process_once
-from ..keyboards import invite_confirm_kb
+from ..keyboards import contact_request_kb
+from ..ops_alerts import alert_ops, mask
 from ..replies import answer_quietly
+from .channels import build_channels_router
```

New texts (replace `NOT_LINKED`, `INVITE_PROBLEMS`, `ONBOARDED`, `ALREADY_ONBOARDED`):

```python
ASK_PHONE = (
    "Hi! This is the Ordelo restaurant bot.\n"
    "To get your restaurant's order alerts here, tap <b>Share my phone number</b> below."
)
NOT_YOUR_CONTACT = (
    "Please use the <b>Share my phone number</b> button to share your OWN number. "
    "Forwarded or typed contacts can't be used."
)
NOT_ON_ROSTER = (
    "This number isn't set up as a restaurant admin. Ask your Ordelo contact to add it, then send /start again."
)
NO_LONGER_ADMIN = "This number isn't on any restaurant's admin list any more. Ask your Ordelo contact if that's wrong."
TUID_TAKEN = "This Telegram account is already linked to another admin. Please contact Ordelo."
BAD_PHONE = "That number doesn't look like a mobile number we can use. Please contact Ordelo."
INVITE_RETIRED = "Invite links aren't used any more. Tap <b>Share my phone number</b> below to link this chat."
LEGACY_LINKED = (
    "You're linked through an old invite link. Tap <b>Share my phone number</b> below to switch to the new link; "
    "old invite links stop working soon."
)
CHANNEL_LABELS = {("telegram",): "Telegram", ("whatsapp",): "WhatsApp", ("telegram", "whatsapp"): "Telegram and WhatsApp"}


def restaurants_text(rs) -> str:
    return "\n".join(f"• {escape(r.rest_name)} ({escape(r.rest_ref)})" for r in rs)


def linked_text(out, again: bool) -> str:
    head = "✅ You're already linked." if again else "✅ You're linked."
    where = CHANNEL_LABELS.get(tuple(sorted(out.channels)), ", ".join(out.channels))
    return f"{head}\n{restaurants_text(out.restaurants)}\nOrder alerts: <b>{where}</b>. Change with /channels."
```

`cmd_start` (any payload; `/start <old invite code>` is treated as retired):

```python
async def cmd_start(message: Message, command: CommandObject, tgram_settings: TgramBotSettings):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user = message.from_user
    try:
        prof = await admin_links.profile(user.id)
        legacy = [] if prof.result != "not_linked" else await invites.linked_restaurants(tgram_settings.bot_key, user.id)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: /start profile lookup failed for user {user.id}")
        await message.answer(TROUBLE)
        return
    if prof.is_admin:
        await message.answer(linked_text(prof, again=True))
    elif prof.result == "not_on_roster":
        await message.answer(NO_LONGER_ADMIN)
    elif legacy:                                           # TRANSITION (P3 removes)
        await message.answer(LEGACY_LINKED, reply_markup=contact_request_kb())
    elif command.args and command.args.strip() not in ("", "admin"):
        await message.answer(INVITE_RETIRED, reply_markup=contact_request_kb())
    else:
        await message.answer(ASK_PHONE, reply_markup=contact_request_kb())
```

`on_contact` (new; same shape as the rider bot's `on_contact` / `_link_contact`, `channels/telegram/rider/router.py`
lines ~118-165):

```python
async def on_contact(message: Message, tgram_settings: TgramBotSettings, event_update: Update):
    if message.chat.type != "private":
        await message.answer(PRIVATE_ONLY)
        return
    user, contact = message.from_user, message.contact
    if contact.user_id is None or contact.user_id != user.id:
        await message.answer(NOT_YOUR_CONTACT, reply_markup=contact_request_kb())
        return
    await process_once(tgram_settings.bot_key, event_update, user.id, lambda: _link_contact(message, tgram_settings))


async def _link_contact(message: Message, tgram_settings: TgramBotSettings):
    user, contact = message.from_user, message.contact
    try:
        out = await admin_links.link(user.id, message.chat.id, contact.phone_number, user.username, user.first_name)
    except Exception:
        logger.exception(f"telegram[{tgram_settings.bot_key}]: admin link failed for user {user.id}")
        await message.answer(TROUBLE, reply_markup=ReplyKeyboardRemove())
        return
    who = f"@{user.username}" if user.username else (user.first_name or str(user.id))
    if out.result == "not_on_roster":
        await message.answer(NOT_ON_ROSTER, reply_markup=ReplyKeyboardRemove())
        await alert_ops(f"Restaurant bot: Telegram {who} ({user.id}) shared {mask(contact.phone_number)}, which is on no "
                        "restaurant's admin list. Refused; add it in sys-admin if they should be an admin.")
        return
    if out.result == "tuid_taken":
        await message.answer(TUID_TAKEN, reply_markup=ReplyKeyboardRemove())
        await alert_ops(f"Restaurant bot: Telegram {who} ({user.id}) shared {mask(contact.phone_number)} but is already "
                        f"linked to admin …{out.phone_last4 or '?'}. Refused; please check.")
        return
    if out.result == "bad_phone":
        await message.answer(BAD_PHONE, reply_markup=ReplyKeyboardRemove())
        return
    if out.result == "relinked":
        prev = f"@{out.previous_username}" if out.previous_username else str(out.previous_tuid)
        await alert_ops(f"Restaurant bot: admin {mask(out.phone)} re-linked from Telegram {prev} to {who}.")
    await message.answer(linked_text(out, again=out.result == "already_linked"), reply_markup=ReplyKeyboardRemove())
```

Old invite confirmation buttons (TRANSITION, P3 removes): `_apply_invite_decision` no longer claims.

```diff
 async def _apply_invite_decision(query, callback_data, tgram_settings):
-    bot_key, user = tgram_settings.bot_key, query.from_user
-    if callback_data.action == "n":
-        ...
-    try:
-        outcome = await invites.claim_invite(...)
-    ...
+    await _finish(query, "Invite links aren't used any more.")
+    await query.bot.send_message(query.from_user.id, INVITE_RETIRED, reply_markup=contact_request_kb())
```

and `on_invite_decision` no longer needs `process_once` (nothing is written). `cmd_whoami`: replace the
`invites.linked_restaurants` call by `admin_links.profile`, keeping the legacy line during the transition:

```python
    lines = [..., f"Ordelo link: {escape(link_line)}", f"Order alerts: {escape(channels_line)}"]
```

`build_router()`:

```diff
     router.message.register(cmd_start, CommandStart())
+    router.message.register(on_contact, F.contact)
     router.message.register(cmd_help, Command("help"))
     router.message.register(cmd_whoami, Command("whoami"))
     router.callback_query.register(on_invite_decision, InviteDecision.filter())   # TRANSITION (P3 removes)
     router.include_router(build_orders_router())
     router.include_router(build_pauses_router())
+    router.include_router(build_channels_router())   # /channels + ac1: taps
     last = Router(name="rest_admin_fallback")
```

Module docstring: replace the "Linking flow" paragraph with the contact-share flow and the result table.

### 5.5 `/channels` (new `channels/telegram/rest_admin/channels.py`, `callbacks.py`, `keyboards.py`, `commands.py`)

```python
# channels/telegram/callbacks.py
class AdminChannels(CallbackData, prefix="ac1"):
    """A channel choice under /channels on the restaurant bot: 't' Telegram only, 'w' WhatsApp only, 'b' both (D6).

    Carries no authority: the handler finds the admin record by the tapping person's from_user.id (t_admin_profile)."""

    c: Literal["t", "w", "b"]
```

```python
# channels/telegram/keyboards.py
CHANNEL_CHOICES = {"t": ("📲 Telegram only", ["telegram"]), "w": ("💬 WhatsApp only", ["whatsapp"]),
                   "b": ("🔁 Both", ["telegram", "whatsapp"])}


def admin_channels_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, (label, _) in CHANNEL_CHOICES.items():
        b.button(text=label, callback_data=AdminChannels(c=code).pack())
    b.adjust(1)
    return b.as_markup()
```

`rest_admin/channels.py`: `/channels` -> `admin_links.profile(tuid)`; not linked -> `ASK_PHONE` + contact button; else
"Order alerts now: <b>X</b>. Where should they go?" + `admin_channels_kb()`. Tap `ac1:<c>` -> `process_once(...)` ->
profile -> `admin_roster.set_channels(prof.phone, CHANNEL_CHOICES[c][1], by=f"telegram:{tuid}")` -> edit the message to
"✅ Order alerts: <b>X</b>." Results `not_found` / `not_linked` -> `ASK_PHONE`. Until P2 ships, append
"<i>(WhatsApp follows this from <date of P2>)</i>" only if the owner wants it; otherwise ship /channels in P2.

`commands.py`:

```diff
 REST_ADMIN_COMMANDS: list[BotCommand] = [
-    BotCommand(command="start", description="Start / link this chat to your restaurant"),
+    BotCommand(command="start", description="Link this chat: share your phone number"),
+    BotCommand(command="channels", description="Choose Telegram, WhatsApp or both for alerts"),
     BotCommand(command="off", description="Pause new order alerts here for a while"),
```

### 5.6 P1 Python tests

| File | Tests |
|---|---|
| `tests/channels/telegram/conftest.py` | `FakeAdminDb` mimicking `t_admin_link`, `t_admin_profile`, `admin_set_channels` result shapes (all six link results); fixture `admin_db`; keep `FakeInviteDb` for TRANSITION tests |
| `tests/channels/telegram/test_admin_links.py` (new) | each result parses; `restaurants` becomes a tuple of `AdminRestaurant`; unexpected shape raises |
| `tests/channels/telegram/test_rest_admin_router.py` | `/start` unlinked -> `ASK_PHONE` + `request_contact` button; linked -> restaurants + channels; `not_on_roster` profile -> `NO_LONGER_ADMIN`; legacy invite -> `LEGACY_LINKED`; `/start <code>` -> `INVITE_RETIRED`; forwarded contact refused, no RPC, no inbox row; verified contact uses `process_once` (duplicate update skipped); each link result's text; ops alert for `not_on_roster`, `tuid_taken`, `relinked`, never for `linked`/`already_linked`; group chat -> `PRIVATE_ONLY`; old `inv:` Yes tap -> retired text, `t_claim_invite` never called. Replace `test_start_says_not_linked` (asserted "isn't linked") |
| `tests/channels/telegram/test_rest_admin_channels.py` (new) | `/channels` unlinked/linked; each `ac1:` tap calls `admin_set_channels` with the right array and `by`; `bad`/`not_linked` results; callback fits 64 bytes (`fits_callback_limit`) |
| `tests/ordelo/test_admin_roster.py` (new) | `whatsapp_phones`: RPC order kept; RPC raises -> fallback list deduped in order; `rest_ref=None` -> fallback; fallback None -> `RestaurantMaster.get_admins_for` |
| `tests/channels/telegram/test_bots.py` | menu contains `/channels`; restaurant router still has no rider handlers |

### 5.7 P1 SQL tests (isolated DB: `ORDELO_TEST_DB_URI`, skill `ordelo-sql-test-db`)

`tests/sql/test_admin_roster_sql.py` (new), against the real files:

- `admin_phone_digits`: `'+44 7700 900123'` -> digits; 7 and 16 digits -> NULL.
- `admin_roster`: list order kept (`ord`); invalid entries dropped; a phone on ELAS and STRK gives two rows; record joins
  by digits even if `admins[]` holds `'+44...'`.
- `t_admin_link`: every result (`linked` sets `{telegram}`; `already_linked` keeps channels and refreshes tcid/username;
  `relinked` keeps channels and returns previous ids; `not_on_roster` writes nothing; `tuid_taken`; `bad_phone`);
  a phone on two restaurants returns both; concurrent link of two phones with one tuid -> one `tuid_taken` (two
  connections, as `test_rider_onboarding_sql.py` does).
- `t_admin_profile`: `not_linked`, `ok`, `not_on_roster` after `array_remove` from `admins`.
- `admin_set_channels` / `admin_unlink_telegram`: results; `telegram` refused when unlinked; unlink returns to `{whatsapp}`.
- `admin_recipients`: WhatsApp = unlinked + linked-with-whatsapp, in `admins[]` order; Telegram = linked-with-telegram;
  paused admin left out of **both** (D9); phone removed from list left out.
- Transition semantics (P1/P2): invite-only admin appears in `t_order_card_destinations` / `t_alert_destinations`
  exactly as before; once that phone has a record the invite row stops counting; a record with `{whatsapp}` is in
  `t_order_card_destinations` (may tap) but not in `t_alert_destinations` (gets nothing new); `t_order_admin_phone` and
  `restaurant_admin_label` prefer the record; `t_admin_pause` / `t_admin_resume` / `t_admin_pause_status` work for a
  record-only admin and for an invite-only admin.
- Grants: anon/authenticated cannot select `restaurant_admin` / `admin_roster` or execute any new function.

Existing SQL tests that insert `t_invites` rows (`test_order_cards_sql.py`, `test_order_taps_sql.py`,
`test_admin_pauses_sql.py`, `test_restaurant_ready_adjust_notices_sql.py`, `test_restaurant_decision_sql.py`) must pass
**unchanged** in P1 (that is the proof the transition branch preserves behaviour). In P3 their fixtures switch to
`restaurant_admin` rows (section 7).

`tests/sql/test_admin_roster_p1_migration_sql.py` (new; pattern `test_rider_telegram_r5_r6_migration_sql.py`): the
PRE-CHECK and VERIFY blocks run and VERIFY 2 equals PRE-CHECK 2 on a database with claimed invites and no records.

---

## 6. P2: WhatsApp honours channels (code only)

### 6.1 The seam: every restaurant-facing WhatsApp send goes through `restaurant_notifier`

Today WhatsApp recipients are resolved in nine places: `delivery_hooks.py` (`delivery_timedout`,
`_handle_restaurant_unconfirmed`, `_handle_restaurant_accept`, the availability enquiry), `takeaway_hooks.py` (two
loops), `location_hooks.py` (rider nearby), `wa_senders.admin_order_reciept` and `wa_senders.admin_delivery_completed`
(their own `RestaurantMaster` lookups); the other notifier notices take the list from their callers. P2 makes
`utils_common/notify/restaurant_notifier.py` the only module that sends restaurant-facing WhatsApp, and its
`_WhatsAppAdapter` the only place that asks the roster. Four notices are added so the hooks stop sending directly:

| New notice | Today's WhatsApp call (must stay byte-identical) | Telegram side |
|---|---|---|
| `ConfirmationRequest(rest_ref, admins, order_number, order_amount, order_items, order_time, order_type)` | `send_restaurant_order_confirmation(recipient=..., ...)` per admin (`delivery_hooks.py` 1372-1385, `takeaway_hooks.py` 176-186) | no-op: the order card is sent by `job_t_order_alerts` |
| `PickupTimeRequest(rest_ref, admins, header, text, order_number, order_time_epoch, intervals_mins)` | `send_restaurant_pickup_time(...)` per admin (`delivery_hooks.py` 1427-1435, `takeaway_hooks.py` 207-215) | no-op: the card shows pickup buttons |
| `NoRiderFound(order_number, rest_ref)` | `_async_wa_client.send_message(to=admin, text="No Rider Found for order number: " + order_number)` (`delivery_hooks.py` 856-861) | **new**: `Notices.send(rest_ref, "🚫 No rider found for <b>…</b>.", notice="no_rider", order=OrderRef(n, "delivery"), reply_to="card")` |
| `RiderNearby(order_number, rest_ref, rest_confirmation_code)` | `send_message(to=admin, text=f"Rider is nearby for order {n}, please have the food ready. 2 Digit Code: *{code}*")` (`location_hooks.py` 288-298) | **new**: `Notices.send(..., notice="rider_nearby", reply_to="receipt")`, text = `_bold(<same WhatsApp text>)` |

The two new Telegram notices are required, not optional: without them a Telegram-only admin would silently lose "No
Rider Found" and "Rider is nearby" (both WhatsApp-only today). `t_notice_sent` stores the `notice` string as data; no SQL
change is needed (check `t_sent_messages` has no CHECK on that column before merging).

### 6.2 `_WhatsAppAdapter` diff

```diff
 class _WhatsAppAdapter:
     async def send(self, notice: Notice) -> None:
+        # The ONE place WhatsApp recipients are decided (D6, D9). whatsapp_phones() never raises and falls back to
+        # today's admins list, so a roster fault can only cause a duplicate, never silence (owner rule 2).
+        rest_ref = _rest_ref_of(notice)
         if isinstance(notice, KitchenReceipt):
-            await wa_senders.admin_order_reciept(delivery_summary=notice.delivery_summary, rider_master=notice.rider_master)
+            admins = await admin_roster.whatsapp_phones(rest_ref)
+            await wa_senders.admin_order_reciept(
+                delivery_summary=notice.delivery_summary, rider_master=notice.rider_master, admins=admins)
         elif isinstance(notice, TakeawayReceipt):
             await wa_senders.takeaway_admin_order_receipt(
                 order_number=notice.order_number,
                 pickup_time=notice.pickup_time,
                 rest_name=notice.rest_name,
-                admins=notice.admins,
+                admins=await admin_roster.whatsapp_phones(rest_ref, fallback=notice.admins),
                 restaurant_msg_id=notice.restaurant_msg_id,
                 rest_ref=notice.rest_ref,
             )
         elif isinstance(notice, AutoAccepted):
             await wa_senders.admin_auto_accept_notice(
-                notice.admins, notice.order_number, notice.pickup_display, notice.pickup_minutes
+                await admin_roster.whatsapp_phones(rest_ref, fallback=notice.admins),
+                notice.order_number, notice.pickup_display, notice.pickup_minutes
             )
         elif isinstance(notice, RiderAlert):
             await wa_senders.notify_rest_admins_rider_alert(
                 ...
-                rest_admins=notice.rest_admins,
+                rest_admins=await admin_roster.whatsapp_phones(rest_ref, fallback=notice.rest_admins),
             )
         elif isinstance(notice, DeliveryCompleted):
-            await wa_senders.admin_delivery_completed(notice.order_number, notice.rest_ref)
+            await wa_senders.admin_delivery_completed(
+                notice.order_number, notice.rest_ref, admins=await admin_roster.whatsapp_phones(rest_ref))
         elif isinstance(notice, Feedback):
-            await self._feedback(notice)
+            await self._feedback(notice, await admin_roster.whatsapp_phones(rest_ref, fallback=notice.admins))
+        elif isinstance(notice, ConfirmationRequest):
+            for admin in await admin_roster.whatsapp_phones(rest_ref, fallback=notice.admins):
+                await wa_senders.send_restaurant_order_confirmation(
+                    recipient=admin, order_number=notice.order_number, order_amount=notice.order_amount,
+                    order_items=notice.order_items, order_time=notice.order_time, order_type=notice.order_type)
+        elif isinstance(notice, PickupTimeRequest):
+            for admin in await admin_roster.whatsapp_phones(rest_ref, fallback=notice.admins):
+                await wa_senders.send_restaurant_pickup_time(
+                    recipient=admin, header=notice.header, text=notice.text, order_number=notice.order_number,
+                    order_time_epoch=notice.order_time_epoch, intervals_mins=list(notice.intervals_mins))
+        elif isinstance(notice, NoRiderFound):
+            for admin in await admin_roster.whatsapp_phones(rest_ref):
+                await wa_senders.admin_no_rider_found(admin, notice.order_number)
+        elif isinstance(notice, RiderNearby):
+            for admin in await admin_roster.whatsapp_phones(rest_ref):
+                await wa_senders.admin_rider_nearby(admin, notice.order_number, notice.rest_confirmation_code)
```

`_rest_ref_of(notice)`: `notice.rest_ref` where present; `KitchenReceipt` -> `notice.delivery_summary.rest_ref`.
`_feedback(notice, admins)` iterates `admins` instead of `notice.admins`.

Per-admin error isolation: `send_restaurant_order_confirmation` / `send_restaurant_pickup_time` raise today and the hook
loop stops at the first failure. Keep that exact behaviour (no try/except added) unless the owner wants isolation; note
it in `docs/to-do.md` either way.

### 6.3 `wa_senders.py` diffs (recipients only; text untouched)

```diff
-async def admin_delivery_completed(order_number: str, rest_ref: str) -> None:
+async def admin_delivery_completed(order_number: str, rest_ref: str, admins: list[str] | None = None) -> None:
     """Tell the restaurant's admins a delivery is completed (rider entered the right customer code)."""
-    admins = await asyncio.to_thread(RestaurantMaster.get_admins_for, rest_ref)
+    if admins is None:  # callers outside the notifier keep today's lookup
+        admins = await asyncio.to_thread(RestaurantMaster.get_admins_for, rest_ref)
```

```diff
 async def admin_order_reciept(
     delivery_summary: DeliverySummary,
     rider_master: dict,
+    admins: list[str] | None = None,
 ):
 ...
     _restaurant_master = RestaurantMaster.from_rest_ref(rest_ref)
-    rest_admins = _restaurant_master.get_admins()
+    rest_admins = _restaurant_master.get_admins() if admins is None else admins
```

New, moved verbatim from the hooks:

```python
async def admin_no_rider_found(admin: str, order_number: str) -> None:
    await _async_wa_client.send_message(to=admin, text="No Rider Found for order number: " + order_number)


async def admin_rider_nearby(admin: str, order_number: str, rest_confirmation_code) -> None:
    await _async_wa_client.send_message(
        to=admin,
        text=f"Rider is nearby for order {order_number}, please have the food ready. 2 Digit Code: *{rest_confirmation_code}*",
    )
```

### 6.4 Hook diffs

`watomation/routers/delivery_hooks.py`

```diff
 async def _handle_restaurant_unconfirmed(...):
     ...
-    # Send restaurant order confirmation to all admins
-    admin_phones = restaurant_master.admins
-    order_type = food_order.action
-    for admin_phone in admin_phones:
-        await send_restaurant_order_confirmation(
-            recipient=admin_phone,
-            order_number=food_order.order_number,
-            order_amount=order_amount,
-            order_items=order_items_str,
-            order_time=order_time_epoch,
-            order_type=order_type,
-        )
-        logger.info(...)
+    # WhatsApp prompt to the admins who get WhatsApp (Telegram admins get the order card from job_t_order_alerts).
+    await restaurant_notifier.notify(ConfirmationRequest(
+        rest_ref=restaurant_master.rest_ref, admins=restaurant_master.admins, order_number=food_order.order_number,
+        order_amount=order_amount, order_items=order_items_str, order_time=order_time_epoch,
+        order_type=food_order.action))
     return {"status": "success", "action": "confirmation_sent", "order_number": food_order.order_number,
-            "sent_to": admin_phones}
+            "sent_to": restaurant_master.admins}   # unchanged meaning: the list it was offered to
```

Same pattern for `_handle_restaurant_accept` (PickupTimeRequest, `intervals_mins=[5, 15, 25]`), `delivery_timedout`
(lines 852-866: keep the `configured_auto` skip around it; `NoRiderFound(order_number, rest_ref)`), and
`takeaway_hooks.py` `_handle_restaurant_unconfirmed` / `_handle_restaurant_accept`. `location_hooks.py` lines 288-298 ->
`RiderNearby`. `customer_hooks.submit_restaurant_feedback` keeps its 503 when `admins` is empty (membership, D3) and
passes `admins` in `Feedback` as today; the adapter filters.

**Unchanged on purpose (membership checks, not sends):** the `if not restaurant_master.admins` guards
(`delivery_hooks.py` 1696, `takeaway_hooks.py` 367), `_handle_restaurant_timedout(..., restaurant_master.admins)`
arguments, `wa_location._validate_demand`, `rest_admin_auth_session.mint_dashboard_session`,
`fapp_ordelo_agent.get_restaurant_details`.

`notify()` runs both adapters with `asyncio.gather` and never raises (today's contract). The hooks previously raised on
a WhatsApp send error inside a background task (logged by FastAPI); now the notifier logs it. Same user-visible result.

**Admin availability enquiry** (`delivery_hooks.py` 1134-1165, the daily 11:00 template that keeps the WhatsApp 24-hour
window open): only admins who get WhatsApp should receive it.

```diff
     admin_rest_refs: dict = {}
     for rest_ref, admins in restaurant_admins.items():
-        for admin in admins:
+        for admin in await admin_roster.whatsapp_phones(rest_ref, fallback=admins):
             admin_rest_refs.setdefault(admin, []).append(rest_ref)
```

(The hook is `async`, so this is fine; a paused admin is skipped too.)

### 6.5 P2 texts

- `channels/telegram/rest_admin/pauses.py` line 40: `TELEGRAM_ONLY = "<i>This pauses Telegram alerts only..."` ->
  `ALL_CHANNELS = "<i>This pauses your alerts on Telegram and WhatsApp. Cards already here keep updating.</i>"`; module
  docstring lines 8-10 likewise. `ordelo/pause_notices.py` line 7 comment.
- `rest_admin/router.py` `linked_text`: add "WhatsApp alerts stop now that you're on Telegram." when `channels == ("telegram",)`.

### 6.6 P2 tests (the regression net for owner rule 2)

| File | Tests |
|---|---|
| `tests/regressions/test_admin_channels_whatsapp_unchanged.py` (new) | Golden recipient test for **every** restaurant-facing WhatsApp send path (ConfirmationRequest, PickupTimeRequest, KitchenReceipt, TakeawayReceipt, AutoAccepted, RiderAlert, DeliveryCompleted, Feedback, NoRiderFound, RiderNearby, availability enquiry). For each: (a) roster fake returns exactly `admins[]` -> the recorded `wa_senders` / `_async_wa_client` calls equal today's (same args, same order, same text); (b) one admin Telegram-only -> only that admin missing, the rest identical; (c) roster raises -> identical to (a); (d) every admin Telegram-only -> no WhatsApp call, and the Telegram adapter still called |
| `tests/utils_common/test_restaurant_notifier.py` | new notices map to the right WhatsApp call and Telegram call (`ConfirmationRequest` / `PickupTimeRequest` Telegram no-op; `NoRiderFound` reply_to card; `RiderNearby` reply_to receipt, HTML-escaped bold); existing "exactly today's call" tests keep passing with a roster fake that returns `admins[]` |
| `tests/watomation/routers/test_delivery_hooks.py`, `test_takeaway_hooks.py`, `test_location_hooks.py`, `test_customer_hooks.py` | hooks now call `restaurant_notifier.notify` with the right notice; existing assertions on `send_restaurant_order_confirmation` / `send_restaurant_pickup_time` args stay valid through `use_adapters` with a real WhatsApp adapter and a roster fake; membership guards unchanged (`No restaurant contacts` when `admins` empty) |
| `tests/utils_common/waba_utils/test_wa_senders.py`, `tests/regressions/test_p7_wa_senders.py` | `admin_order_reciept(admins=None)` and `admin_delivery_completed(admins=None)` unchanged; with `admins=[...]` only those recipients; new senders' text byte-identical to the moved strings |

---

## 7. P3: cut-over (date chosen by the owner)

SQL (`migrations/admin_roster_p3_cutover.sql`, the owner applies):

1. PRE-CHECK: who would lose Telegram (claimed invites whose phone has no record):
   ```sql
   SELECT i.rest_ref, right(i.phone_number, 4) AS phone_last4, i.telegram_first_name, i.claimed_at
     FROM public.t_invites i
    WHERE i.status = 'claimed'
      AND NOT EXISTS (SELECT 1 FROM public.restaurant_admin ra WHERE ra.phone = public.admin_phone_digits(i.phone_number));
   ```
   These people drop to WhatsApp-only (D7). Message them the bot link first if wanted.
2. Apply the P3 versions of `telegram/t_order_alerts.sql`, `restaurant_admin/restaurant_order_decision.sql`,
   `telegram/t_admin_pauses.sql`, `restaurant_admin/admin_roster.sql` (every `-- TRANSITION (P3 removes)` branch deleted;
   `admin_roster_status` loses `legacy_invite`).
3. Deploy the P3 code.
4. Cleanup (owner approval; drops are not reversible except from git):
   ```sql
   DROP FUNCTION IF EXISTS public.t_claim_invite (text, text, bigint, bigint, text, text);
   DROP FUNCTION IF EXISTS public.t_invite_preview (text, text, bigint);
   DROP FUNCTION IF EXISTS public.t_linked_restaurants (text, bigint);
   DROP VIEW IF EXISTS public.t_invites_shareable;
   ```
   Keep the `t_invites` table (read-only audit, RLS on, no grants). `telegram/t_invites.sql` then documents only the
   table (header `LIVE CHECK`: "functions dropped <date>, table kept as audit"); per the SQL standard a dropped object's
   definition moves to `ordelo_datamodels/_archive/`.
5. VERIFY: no function body mentions `t_invites` any more: `SELECT proname FROM pg_proc WHERE prosrc LIKE '%t_invites%';` -> 0 rows.
6. `drift_check.py`, `build_guide.py`.

Code: delete `channels/telegram/invites.py`, `InviteDecision` (`callbacks.py`), `invite_confirm_kb` (`keyboards.py`),
`on_invite_decision` / `_handle_invite_decision` / `_apply_invite_decision` / `LEGACY_LINKED` / `invites` import in the
router, `tests/channels/telegram/test_invites.py`, `FakeInviteDb`. SQL test fixtures that insert `t_invites` rows switch
to `INSERT INTO restaurant_admin (phone, channels, tuid, tcid, t_first_name) VALUES (...)`.
`database-operations` skill: delete the "Telegram Invites" SOP (section 6.2 below replaces it in P1).

---

## 8. restaurant-frontend (P1)

Follow its `CLAUDE.md` (Next.js 14, `NextResponse`, 2-space, PR with screenshots).

### 8.1 `app/api/sys-admin/restaurants/_lib/validate.ts` (admins normalisation, D13)

```diff
-                const trimmed = raw.trim().replace(/^\+/, '')
-                if (trimmed.length === 0) continue
+                const trimmed = raw.replace(/\D/g, '')          // same rule as SQL admin_phone_digits()
+                if (trimmed.length === 0) continue
+                if (trimmed.length < 8 || trimmed.length > 15) {
+                    errors.push({ field: 'admins', message: `"${raw}" is not a phone number (8-15 digits)` })
+                    break
+                }
```

Test: `app/api/sys-admin/restaurants/_lib/validate.test.ts` (new, Vitest): `'+44 7700 900123'` -> `'447700900123'`;
duplicates after normalising removed; 7 digits rejected.

### 8.2 `app/api/sys-admin/restaurants/[rest_ref]/admins/route.ts` (new)

- `GET` -> `sb.rpc('admin_roster_status', { p_rest_ref })` plus the bot username
  (`ordelo_config` row `TGRAM_REST_ADMIN_BOT_USERNAME`) -> `{ admins: [...], bot_link: "https://t.me/<username>?start=admin" }`.
- `app/api/sys-admin/restaurants/[rest_ref]/admins/[phone]/route.ts`:
  `PATCH { channels: ('whatsapp'|'telegram')[] }` -> `sb.rpc('admin_set_channels', { p_phone, p_channels, p_by: 'sys-admin' })`;
  `POST .../unlink` (separate file `[phone]/unlink/route.ts`) -> `sb.rpc('admin_unlink_telegram', { p_phone, p_by: 'sys-admin' })`.
  Map `result` to HTTP: `ok` 200, `not_found` 404, `bad_channels` 400, `not_linked` 409. `console.log('[sys_admin.admins.*]', ...)`
  like the existing PATCH. The sys-admin client uses `SUPABASE_SECRET_KEY` (`lib/sys-admin-session.ts` `rawClient()`), and
  its Proxy only intercepts `.from`, so `.rpc` reaches the service-role-only functions.

### 8.3 `app/sys-admin/restaurants/page.tsx` (Admins card, lines ~430-475)

Replace the chip list with one row per entry of `admins` from the new GET (fetched after the restaurant loads and after
every save of `admins`):

- phone (mono), and a red "not a valid phone" badge when `valid === false`;
- Telegram: "Linked as @username (First) · <date>" or "Not linked"; during P1/P2 "Old invite" grey badge when `legacy_invite`;
- channels: segmented control **WhatsApp | Telegram | Both**; Telegram and Both disabled unless linked;
- "Paused" badge when `paused`;
- "Unlink Telegram" (confirm dialog) when linked;
- the existing remove (trash) button unchanged (it edits `admins[]`, the authority).

Above the list: **Copy bot link** (copies `bot_link`) and **Copy message**, which copies:
"Get Ordelo order alerts on Telegram: open <bot_link> and tap Share my phone number. It works only from the number we
have for you."

---

## 9. Testing with the owner's SQL harnesses

### 9.1 `test_support/test_restaurant_notices.sql` (existing; covers order cards, receipts, notices, both channels)

It already proves every restaurant-facing message on both channels. The roster changes **who** receives them, so it is
run as a matrix with the owner's own phone (`447448440754`, an admin of STRK) in three channel modes. The channel is set
with `test_admin_onboarding.sql` STAGE 12 (keeps this script's writes scoped to STRK-TEST rows).

Changes to the script (and `tests/sql/test_restaurant_notices_script_sql.py` in the same commit, per
`docs/live-order-test-harness.md`):

1. Header PREREQUISITES: replace "A CLAIMED t_invites row for rest_ref 'STRK' ..." with "Your Telegram linked by sharing
   your number (test_admin_onboarding.sql STAGE 12). Until P3 an old claimed STRK invite also works."
2. PREREQUISITES CHECK: add read-only columns
   ```sql
   (SELECT channels FROM public.restaurant_admin WHERE phone = '447448440754')      AS owner_channels,      -- {telegram} / {whatsapp} / both
   (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp'))                AS whatsapp_recipients,
   (SELECT count(*) FROM public.t_alert_destinations('rest_admin', 'STRK'))          AS telegram_recipients,
   ```
3. New **STAGE 11: NO RIDER FOUND** (P2), run after STAGE 1 + your Accept + pickup time (STAGE 2), **without** STAGE 2b,
   so no rider job exists. A `DO $$` block picks the newest accepted fake order and times it out:
   ```sql
   DO $$
   DECLARE v_no text;
   BEGIN
       SELECT order_number INTO v_no FROM public.delivery_summary
        WHERE order_number LIKE 'STRK-TEST-%' AND status = 'unassigned' ORDER BY dtts DESC LIMIT 1;
       IF v_no IS NULL THEN
           RAISE EXCEPTION 'STAGE 11: run STAGE 1 and accept + choose a pickup time first (status must be unassigned)';
       END IF;
       UPDATE public.delivery_summary SET status = 'timedout' WHERE order_number = v_no;
   END $$;
   ```
   Only `status` changes (changing `restaurant_confirmation_status` would fire the confirmation webhook again). The
   trigger `trigger_delivery_summary_timedout` POSTs `/delivery-hooks/delivery-timedout`. Expect "No Rider Found for
   order number: …" on WhatsApp for WhatsApp admins and the new 🚫 notice (reply to the card) on Telegram. The payment
   cancel goes to the TEST service and fails softly (`test_p7d_test_order_safety.py` already proves the cancel path);
   the customer is your own WhatsApp. The `WHERE order_number = v_no` form satisfies
   `test_every_delete_and_update_is_scoped_to_strk_test_rows`.
4. New **STAGE 12: RIDER NEARBY** (P2, terminal, not SQL), after STAGE 3:
   ```
   curl -X POST "$ORDELO_APP_URL/location-hooks/notify-rider-location-event" -H 'Content-Type: application/json' \
        -d '{"event": "enter", "rid": "rest", "order_number": "<STRK-TEST-… from STAGE 1>"}'
   ```
   Expect "Rider is nearby … 2 Digit Code: *47*" on WhatsApp, and the 🛵 notice replying to the receipt on Telegram.
5. Stage list in `test_the_script_has_every_stage_the_plan_promises`: add `"STAGE 11", "STAGE 12"`.
6. `docs/live-order-test-harness.md`: stages table rows 11-12, a "Channel matrix" section (below), the prerequisite row.

**Channel matrix (the regression run the owner cares about).** Run STAGE 0-10 (and 11-12 from P2) three times:

| Owner channels (set in onboarding STAGE 12) | Expect on WhatsApp | Expect on Telegram |
|---|---|---|
| no record / `{whatsapp}` (P1: also an old invite) | **everything exactly as before** (the WhatsApp regression pass in `live-order-test-harness.md`) | P1: as before if an invite is claimed; P2+: nothing new |
| `{telegram}` | P1: as before. **P2+: nothing** (no prompt, receipt, notices, no-rider, rider-nearby, 11:00 enquiry) | every card, receipt and notice |
| `{telegram, whatsapp}` | everything as before | everything |

Also in each mode: tap on the **other** channel's older message still works (authority is membership, not channel), and
`/off` (P2+) silences both channels; `/on` restores.

**Pre-existing harness issues found while planning (owner decision, not part of this work):** STAGE 0 now contains an
unscoped `update rider_master ... where rider_name in ('lohith', 'lohithNwg')` and an `ordelo_config` upsert of
`overwatch_list` (commit b09eb8a), and the "copy your linked chat to STRK" INSERT is commented out, so
`test_stage0_copies_the_linked_chat_to_strk_only_once` cannot pass as written. Suggest moving the owner-setup statements
into a separate "OWNER SETUP (run once)" block and deleting that test in P3 (invites retired).

### 9.2 `test_support/test_admin_onboarding.sql` (new: what the notices harness cannot cover)

Pattern: `test_support/test_rider_onboarding.sql`. Fake phones `4477009009xx` (Ofcom drama range), fake Telegram ids
`999000000901..999000000999`. Writes: `restaurant_admin` rows of fake phones; `pauses` of fake phones; and the STRK row's
`admins` array **only** by `array_append` / `array_remove` of fake phones (STRK is the test restaurant). STAGE 0 removes
every fake. Offline proof: `tests/sql/test_admin_onboarding_script_sql.py` (every write scoped to `4477009009%` or the
owner's phone in STAGE 12; re-runnable; each stage's expected values).

| Stage | Does | Expect |
|---|---|---|
| PREREQ (read only) | 9 functions present, `restaurant_admin` exists, STRK row exists | 9 / true / true |
| 0 | remove fake phones from STRK `admins`, delete fake `restaurant_admin` and `pauses` rows | 0 left |
| 1 | `t_admin_link(999000000901, …, '447700900901', …)` with the phone on no list | `not_on_roster`; no row |
| 2 | operator adds `447700900901` to STRK (`array_append`) | `admin_recipients('STRK','whatsapp')` has it; `'telegram'` not; `admin_roster_status('STRK')` shows it unlinked |
| 3 | link again | `linked`, channels `{telegram}`; whatsapp recipients lose it, telegram recipients gain it |
| 4 | same account again with a new tcid/username | `already_linked`; tcid refreshed; channels kept |
| 5 | new account 999000000902, same phone | `relinked`, `previous_tuid = 999000000901` |
| 6 | add `447700900903`; link it with tuid 999000000902 | `tuid_taken`; 903 untouched |
| 7 | `admin_set_channels` both / whatsapp / `{}` / `{fax}`; set telegram on unlinked 903 | `ok` / `ok` / `bad_channels` / `bad_channels` / `not_found` |
| 8 | pause 901 (`pause_start('rest_admin', …, 'STRK', '6h', 'operator', 'harness')`) | out of **both** recipient lists; `pause_end` restores |
| 9 | last-admin guard: pause every STRK admin except the fake | `not_allowed` for the last (owner's phone untouched: read the result only) |
| 10 | `array_remove` 901 from STRK | `t_admin_profile` -> `not_on_roster`; `admin_for_tuid` NULL; record kept. Re-add -> back, no re-link |
| 11 | `admin_unlink_telegram('447700900901', 'harness')` | `ok`; channels `{whatsapp}` |
| 12 | **LIVE, your phone** (manual): note your row; open `t.me/OrdeloRestaurantBot?start=admin`, Share my phone number; `/whoami`; `/channels`. Then the channel-matrix SETs: `SELECT admin_set_channels('447448440754', ARRAY['telegram'], 'owner-test');` etc. Undo: `SELECT admin_unlink_telegram('447448440754', 'owner-test');` | bot texts per section 5.4; forwarding someone else's contact refused; an ops line for a number on no list |
| 13 | TRANSITION (P1/P2 only, read only): `t_order_card_destinations('rest_admin','STRK')` lists an invite-only admin; after STAGE 12 your invite no longer counts | as described |

---

## 10. Docs, skills, ADRs (same PR as the code they describe)

| File | Change |
|---|---|
| `CONTEXT.md` | done in the grilling session: Admin roster, Admin record, Admin link, Admin channels, Pause, Telegram invite (retiring) |
| `docs/adr/0011-...md` | Amendment 5 (drafted with this plan) |
| `docs/adr/0013-...md` | Amendment 1 (drafted with this plan) |
| `docs/telegram-layer.md` (+ HTML companion) | §2 request flow -> contact share; §3 file map (`admin_links.py`, `ops_alerts.py`, `rest_admin/channels.py`, `ordelo/admin_roster.py`); §6 rows for every new object (defining file, Python caller, tests); §7 "Invite lifecycle" -> "Admin link lifecycle"; change log |
| `.claude/skills/database-operations/SKILL.md` | replace "Telegram Invites (`t_invites`)" with "Restaurant admins (roster)": `SELECT admin_roster_status('ELAS')`, `admin_set_channels`, `admin_unlink_telegram`, "add an admin = add the phone in sys-admin", "the bot link is fixed"; keep the never-delete rule. Update the skill description ("create/list/revoke Telegram invites" -> "restaurant admin roster and Telegram links") |
| `docs/live-order-test-harness.md` | section 9.1 |
| `docs/to-do.md` | add: WhatsApp 24-hour window when an operator moves a Telegram-only admin back to WhatsApp (free text fails until the 11:00 template); pause "ends soon / back on" messages go to Telegram only; per-admin error isolation for the confirmation and pickup prompts; harness STAGE 0 issues (9.1) |
| `ordelo_datamodels/guide_content.json` | `restaurant_admin` capability gains the roster objects; then `build_guide.py` |
| `notebooks/telegram/tgram_setup_bot.py` | owner step: publish with `BOT_KEY = "rest_admin"` (the working copy currently says `"rider"`, uncommitted) |
| restaurant-agents | nothing (its `admins` reads are on its own removal to-do and it sends nothing to admins) |

## 11. Implementation order and checks per PR

**PR 1 (P1)**: `admin_roster.sql` -> SQL tests green on the isolated DB (`ordelo-sql-test-db` skill: start, run
`tests/sql`, stop) -> `t_*` bodies -> **all existing SQL tests still green unchanged** -> migration file + its test ->
Python wrappers -> router + `/channels` -> pytest green -> frontend -> `npm run lint && npm test` -> docs/skill/guide ->
`ruff check .` -> `python scripts/datamodels/build_guide.py` -> `tests/test_datamodels_standard.py`.
Telegram verification: `telegram-vertification-loop` skill (dispatcher, webhook and database contract tests; live
evidence clearly scoped).

**PR 2 (P2)**: notices and adapter -> `tests/regressions/test_admin_channels_whatsapp_unchanged.py` written **first**
against today's code (it must pass before the change, then after) -> hook moves -> full pytest.

**PR 3 (P3)**: deletions only, plus fixture switches; `grep -rn "t_invites\|invites\." channels watomation ordelo utils_common`
returns only the audit-table docs.

Gate before each merge: the owner runs the matrix in 9.1 for that phase and records results as
`boundary | action | observed | label | not verified`.

## Implementation notes (P1, 24 Oct 2026)

Deviations from the plan as written:
- The live harness `test_admin_onboarding.sql` has no last-admin-guard stage; STAGE 11 is a read-only transition check (old invite-only admins still routed) and STAGE 12 is the manual live step.
- `/channels` ships in P1. It shows a note that WhatsApp will follow until P2 sets `WHATSAPP_FOLLOWS_CHANNELS = True`.
- `/start` keeps a legacy-invite path (`/start <code>` for an already-issued code) until P3; the invite Yes button is retired.
- Sys-admin UI falls back to the old chip list when `admin_roster_status` is unavailable (`available:false`), so the page works before the migration is applied.
- Status (25 Oct 2026): P1 applied, deployed and verified live on STRK by the owner (link, channels, pause, Accept/Pickup, WhatsApp unchanged, `test_restaurant_notices.sql`, `test_admin_onboarding.sql` stages 0-11). Lesson: `t_order_alerts.sql` had not fully applied at first; check `destinations_use_roster = true` before live testing. P2 and P3 not started.
