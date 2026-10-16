-- =============================================================================================
-- Feature SQL: Telegram invites (restaurant-admin bot now; the rider bot can reuse the same table)
-- =============================================================================================
-- See also (paths under ordelo_datamodels/): how the linked admins are used to send order cards and kitchen receipts: telegram/t_order_alerts.sql, restaurant_admin/restaurant_ready_adjust_notices.sql.
-- Run once in the Supabase SQL editor. Repeatable: every statement is CREATE OR REPLACE /
-- IF NOT EXISTS / DROP IF EXISTS, so running it again changes nothing.
--
-- WHAT THIS ADDS
--   Tables     t_invites                the one new table: one row per invite link
--   Views      t_invites_shareable      t_invites + the ready-to-send t.me link
--   Functions  t_new_invite_code()      generates the random code (column default)
--              t_invites_normalize_phone()  trigger: keeps phone_number digits-only
--              t_invite_preview()       read-only "what would happen if this person used this code?"
--              t_claim_invite()         atomic claim (first valid caller wins)
--              t_linked_restaurants()   "which restaurants is this Telegram user linked to?"
--
-- HOW THE PIECES FIT TOGETHER (all inside this database)
--
--   restaurant_master (existing)              ordelo_config (existing)
--     rest_ref  PK  <------------------+        config_key = 'TGRAM_<BOT_KEY>_BOT_USERNAME'
--     rest_name                        |        config_value = bot username (no @)
--                                      |                |
--   t_invites (NEW)                    |                | joined by the view only
--     rest_ref  FK ---------------------+                v
--     invite_code PK  <---------- t_invites_shareable (view) = t_invites + invite_link
--     status, expires_at, claimed_at
--     telegram_user_id / telegram_chat_id / username / first name   (filled at claim time)
--
--   * t_invites -> restaurant_master: foreign key on rest_ref, so an invite can only name a
--     real restaurant. The functions join restaurant_master to return rest_name, so the bot can
--     say which restaurant a person is joining without a second query.
--   * t_invites_shareable -> ordelo_config: looks up the bot username so the t.me link can be
--     built without hard-coding the bot into the table. Changing bots = updating one config row.
--   * The three RPC functions are the ONLY way the application touches t_invites. They never
--     modify restaurant_master or ordelo_config.
--   * Nothing here reads or writes restaurant_master.admins (the list of admin phone numbers used
--     by the WhatsApp flows). The invite's phone_number is informational: it records who the
--     operator intended the link for. See "NOT YET DONE" below.
--
-- HOW THE REST OF THE SERVICES USE IT
--
--   You (operator, SQL editor)  --INSERT--> t_invites          creates the invite (code is generated)
--                               --SELECT--> t_invites_shareable  copy the invite_link, send it privately
--                               --UPDATE--> status = 'revoked'      cuts someone off
--
--   Telegram user taps the link  -->  OrdeloAgent FastAPI, POST /telegram/rest-admin/webhook
--     (watomation/routers/telegram_webhook.py -> channels/telegram/rest_admin/router.py)
--     which calls these functions through the Supabase REST client (service key; RLS is bypassed):
--     (Python callers: keep this list in sync with the module docstring of channels/telegram/invites.py.
--      Overview of the whole Telegram layer: docs/telegram-layer.md)
--       /start <code>            -> channels/telegram/invites.py preview_invite()  -> t_invite_preview()
--       taps "Yes"               -> channels/telegram/invites.py claim_invite()    -> t_claim_invite()
--       /start (no code), /whoami-> channels/telegram/invites.py linked_restaurants() -> t_linked_restaurants()
--
--   Customer WhatsApp/web ordering, rider_master, delivery_* tables and the LangGraph rider agent do
--   not read or write any of these objects.
--
-- INVITE LIFECYCLE (t_invites.status)
--
--   pending --(person confirms in the bot, before expires_at)--> claimed
--   pending --(expires_at passes; recorded on the next claim attempt)--> expired
--   pending --(operator sets it)--> revoked
--   claimed --(operator sets it)--> revoked      (the person loses access on their next action)
--   There is no path back to pending: issue a new invite instead. 'expired' is also computed on the
--   fly (expires_at <= now()), so an unclaimed old invite is treated as expired even if its status
--   still says 'pending'.
--
-- SECURITY MODEL
--   * t_invites holds invite secrets and Telegram ids, so row-level security is ON with no
--     policies, and the view and functions are revoked from anon/authenticated. Only the service key
--     used by OrdeloAgent (which bypasses RLS) can read or call them.
--   * A claim proves the person held the link and tapped Yes; it does not prove their phone number.
--     Links are sent privately by the operator, and the operator can see who claimed each one
--     (telegram_username / telegram_first_name) and revoke it.
--   * Claiming is race-safe: one conditional UPDATE decides the winner; a unique index stops the same
--     person holding two claimed invites for the same restaurant and bot.
--
-- NOT YET DONE (so you do not assume it)
--   * phone_verified is never set by any code. It is reserved for a later contact-share flow.
--   * No order action checks t_invites yet. When restaurant actions (accept, pickup time, ready)
--     are added they must re-check that the person's invite is still 'claimed' for that rest_ref,
--     and (decision pending) whether the phone must also be in restaurant_master.admins.
--   * There is no cleanup job; old rows are small and keep the audit trail.
-- =============================================================================================

-- Provides gen_random_bytes() for invite codes. Normally already enabled on Supabase (schema: extensions); harmless if so.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------------------------
-- t_new_invite_code(): the random invite code, used as the column default below.
-- 9 random bytes -> 12 base64 characters; '+' and '/' are swapped for '-' and '_' so the code only
-- contains [A-Za-z0-9_-], which is what Telegram allows in a /start payload (max 64 characters).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_new_invite_code()
RETURNS text LANGUAGE sql VOLATILE SET search_path = public, extensions AS $$
  SELECT translate(rtrim(encode(gen_random_bytes(9), 'base64'), '='), '+/', '-_');
$$;

-- ---------------------------------------------------------------------------------------------
-- TABLE t_invites: one row per invite link. The operator inserts a row (rest_ref + phone_number);
-- everything else is generated or filled in by the bot when the invite is claimed. The same row is
-- the audit trail afterwards: it records who claimed it, from which Telegram account, and when.
-- ---------------------------------------------------------------------------------------------
-- Tokens and Telegram ids are not for the public API: with RLS on and no policies, only the service key
-- (which bypasses RLS) can read or change this table.
CREATE TABLE IF NOT EXISTS public.t_invites (
    -- The secret in the link (t.me/<bot>?start=<invite_code>). Generated by the database.
    invite_code text NOT NULL DEFAULT t_new_invite_code(),
    -- Which Telegram bot the link is for; 'rest_admin' today, e.g. 'rider' later. A code is only
    -- valid for the bot named here, so a restaurant link cannot be used on another bot.
    bot_key text NOT NULL DEFAULT 'rest_admin'::text,
    -- The restaurant the person will be linked to. Must exist in restaurant_master.
    rest_ref character varying(4) NOT NULL,
    -- Who the operator meant the link for (digits only, normalized by the trigger below).
    -- Informational for now: no code compares it to anything yet.
    phone_number text NOT NULL,
    -- Where the invite is in its lifecycle; see INVITE LIFECYCLE at the top of this file.
    status text NOT NULL DEFAULT 'pending'::text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    -- The link stops working after this time. Default 48 hours; override per row if needed.
    expires_at timestamp with time zone NOT NULL DEFAULT (now() + '48:00:00'::interval),
    -- ---- The columns below are empty until the person confirms in the bot (filled in one UPDATE) ----
    claimed_at timestamp with time zone,
    telegram_user_id bigint, -- "TID": Telegram's id for the person (from_user.id); identifies the actor
    telegram_chat_id bigint, -- "TCID": the chat the bot sends messages to (chat.id); equals the user id in private chats
    telegram_username text, -- @handle at claim time; can change later, display only
    telegram_first_name text, -- first name at claim time; lets you spot an unexpected claimer
    -- Reserved for a later flow where the person proves their phone (Telegram contact share). Nothing sets it yet.
    phone_verified boolean NOT NULL DEFAULT false,
    CONSTRAINT t_invites_pkey PRIMARY KEY (invite_code),
    CONSTRAINT t_invites_claimed_has_ids CHECK (((status <> 'claimed'::text) OR ((telegram_user_id IS NOT NULL) AND (telegram_chat_id IS NOT NULL) AND (claimed_at IS NOT NULL)))),
    CONSTRAINT t_invites_phone_digits CHECK ((phone_number ~ '^[0-9]{6,15}$'::text)),
    CONSTRAINT t_invites_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'claimed'::text, 'expired'::text, 'revoked'::text]))),
    CONSTRAINT t_invites_rest_ref_fkey FOREIGN KEY (rest_ref) REFERENCES restaurant_master(rest_ref)
);

-- Index 2: fast "who is this Telegram user?" lookup (t_linked_restaurants, future authorization checks).
CREATE INDEX IF NOT EXISTS t_invites_claimed_by_user ON public.t_invites USING btree (bot_key, telegram_user_id) WHERE (status = 'claimed'::text);

-- Index 1: one claimed link per person per restaurant per bot. A person may serve several restaurants
-- (several rows), but cannot claim two invites for the same one. Also what makes t_claim_invite()
-- answer 'already_linked' instead of creating a duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS t_invites_one_claim_per_user_rest ON public.t_invites USING btree (bot_key, rest_ref, telegram_user_id) WHERE (status = 'claimed'::text);

ALTER TABLE public.t_invites ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------------
-- Trigger: store phone numbers as digits only ('+44 7700 900123' -> '447700900123') so numbers entered
-- in different formats are comparable, and the digits-only CHECK above accepts what you type.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_invites_normalize_phone()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.phone_number := regexp_replace(NEW.phone_number, '\D', '', 'g');
  RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- VIEW t_invites_shareable: t_invites plus invite_link, the URL you send to the person.
-- The bot username is read from ordelo_config (row key 'TGRAM_' || upper(bot_key) || '_BOT_USERNAME'),
-- so switching bots needs no DDL. Set it once:
INSERT INTO ordelo_config (config_key, config_value, description)
  VALUES ('TGRAM_REST_ADMIN_BOT_USERNAME', 'OrdeloRestaurantBot', 'Restaurant-admin Telegram bot')
  ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();

-- If that row is missing, invite_link is NULL (the invite itself still works).
-- security_invoker: the view runs with the caller's rights, so it cannot expose rows that RLS hides.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.t_invites_shareable WITH (security_invoker=true) AS
 SELECT i.invite_code,
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
    (('https://t.me/'::text || c.config_value) || '?start='::text) || i.invite_code AS invite_link
   FROM t_invites i
     LEFT JOIN ordelo_config c ON c.config_key::text = (('TGRAM_'::text || upper(i.bot_key)) || '_BOT_USERNAME'::text);

REVOKE ALL ON TABLE public.t_invites_shareable FROM anon, authenticated;

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
CREATE OR REPLACE FUNCTION public.t_invite_preview(p_code text, p_bot_key text, p_user_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = public AS $$
DECLARE
  r record;
  v_result text;
BEGIN
  -- Join restaurant_master to return the restaurant's display name with the verdict.
  SELECT i.*, rm.rest_name INTO r
  FROM t_invites i JOIN restaurant_master rm ON rm.rest_ref = i.rest_ref
  WHERE i.invite_code = p_code AND i.bot_key = p_bot_key;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('result', 'unknown');
  END IF;

  -- Order matters: a claimed invite is reported as claimed even after its expiry time has passed.
  v_result := CASE
    WHEN r.status = 'revoked' THEN 'revoked'
    WHEN r.status = 'claimed' AND r.telegram_user_id = p_user_id THEN 'claimed_by_you'
    WHEN r.status = 'claimed' THEN 'used'
    WHEN r.status = 'expired' OR r.expires_at <= now() THEN 'expired'
    ELSE 'pending'
  END;

  RETURN jsonb_build_object('result', v_result, 'rest_ref', r.rest_ref, 'rest_name', r.rest_name);
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- Permissions: Supabase grants new functions and views to the public API roles by default. Remove that;
-- only the service key (used by OrdeloAgent) may call these.
-- ---------------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.t_invite_preview(text, text, bigint) FROM PUBLIC, anon, authenticated;

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
CREATE OR REPLACE FUNCTION public.t_claim_invite(
  p_code text, p_bot_key text, p_user_id bigint, p_chat_id bigint,
  p_username text, p_first_name text
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
  v_ref  text;
  v_name text;
BEGIN
  UPDATE t_invites
     SET status = 'claimed', claimed_at = now(),
         telegram_user_id = p_user_id, telegram_chat_id = p_chat_id,
         telegram_username = p_username, telegram_first_name = p_first_name
   WHERE invite_code = p_code AND bot_key = p_bot_key
     AND status = 'pending' AND expires_at > now()
  RETURNING rest_ref INTO v_ref;

  IF FOUND THEN
    SELECT rest_name INTO v_name FROM restaurant_master WHERE rest_ref = v_ref;
    RETURN jsonb_build_object('result', 'ok', 'rest_ref', v_ref, 'rest_name', v_name);
  END IF;

  -- Not claimable: record the expiry (the only status change made on a failed attempt), then report why.
  UPDATE t_invites SET status = 'expired'
   WHERE invite_code = p_code AND bot_key = p_bot_key AND status = 'pending' AND expires_at <= now();
  RETURN t_invite_preview(p_code, p_bot_key, p_user_id);

EXCEPTION WHEN unique_violation THEN
  -- Raised by t_invites_one_claim_per_user_rest: this person is already linked to this restaurant.
  -- The whole block (including the UPDATE) is rolled back, so the invite stays 'pending'.
  RETURN jsonb_build_object('result', 'already_linked');
END;
$$;

REVOKE ALL ON FUNCTION public.t_claim_invite(text, text, bigint, bigint, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- t_linked_restaurants(bot_key, telegram_user_id): the restaurants this Telegram user is currently
-- linked to, as jsonb [{rest_ref, rest_name}, ...] ('[]' if none). Used by /start (no code) and /whoami,
-- and the natural lookup for authorization checks later. Revoked and expired invites do not count.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_linked_restaurants(p_bot_key text, p_user_id bigint)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT coalesce(jsonb_agg(jsonb_build_object('rest_ref', i.rest_ref, 'rest_name', rm.rest_name)
                            ORDER BY rm.rest_name), '[]'::jsonb)
  FROM t_invites i JOIN restaurant_master rm ON rm.rest_ref = i.rest_ref
  WHERE i.bot_key = p_bot_key AND i.telegram_user_id = p_user_id AND i.status = 'claimed';
$$;

REVOKE ALL ON FUNCTION public.t_linked_restaurants(text, bigint) FROM PUBLIC, anon, authenticated;

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- DROP TRIGGER IF EXISTS t_invites_normalize_phone ON public.t_invites;

-- CREATE TRIGGER t_invites_normalize_phone
-- BEFORE INSERT OR UPDATE OF phone_number ON public.t_invites
-- FOR EACH ROW EXECUTE FUNCTION public.t_invites_normalize_phone();

-- ---------------------------------------------------------------------------------------------
-- Day-to-day use (copy into the SQL editor)
-- ---------------------------------------------------------------------------------------------
-- Create an invite (code and 48h expiry are generated):
  
-- INSERT INTO t_invites (rest_ref, phone_number) VALUES ('ELAS', '447448440754')
--   RETURNING invite_code;

-- Get the link to send privately:
  
-- SELECT invite_code, rest_ref, phone_number, status, invite_link FROM t_invites_shareable
--   WHERE status = 'pending' ORDER BY created_at DESC;

-- See who claimed what (check the Telegram name is the person you expected):
  
-- SELECT rest_ref, phone_number, telegram_username, telegram_first_name, telegram_user_id, claimed_at, *
--   FROM t_invites WHERE status = 'claimed';

-- Revoke (works on pending AND claimed invites; takes effect on the person's next action):
--   UPDATE t_invites SET status = 'revoked' WHERE invite_code = '<code>';
