-- =============================================================================================
-- ordelo_datamodels/core/rider_master.sql
-- One row per rider: phone (rider_id), vehicle, town, status, shift flag, channel and Telegram link.
-- =============================================================================================
-- LIVE CHECK    Matches live: migrations/rider_telegram_r1.sql applied by the owner on 2026-10-22 (rider_id NOT NULL + UNIQUE,
--                 channel, tuid, tcid, t_username, t_first_name, t_linked_at, phone_verified, rider_master_tuid_uidx), and the
--                 Telegram onboarding was tested live the same day (existing and new riders).
-- OBJECTS       table  rider_master
--                   Riders that can be offered delivery jobs, keyed by rider_id (their phone number, digits only).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
--               On the existing live table the CREATE TABLE is a no-op: the R1 columns come from migrations/rider_telegram_r1.sql.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   get_available_riders() (dispatch/job_create_dispatch.sql) picks riders here: status = 'active', same town
--                 (case-insensitive), same vehicle_type, is_in_shift = true, not paused (availability/pauses.sql is_paused()), not
--                 already offered this order and not on another job (delivery_inflight); TEST3100 orders only go to riders in
--                 ordelo_config overwatch_list. job_create_dispatch() then ranks by priority.
--                 Daily shift cycle (WhatsApp riders): cron 'enquire_shift_availability' (11:00 UTC) -> enquire_shift_availability()
--                 POSTs the status = 'active' riders -> /delivery-hooks/shift-availability-enquiry sets is_in_shift = false for
--                 them and sends the shift question -> a 'yes' tap sets is_in_shift = true (watomation/on_callback_wa_handler.py).
--                 Telegram riders (channel = 'telegram', from phase R5) leave the daily cycle and use /off with a mandatory end
--                 time instead (availability/pauses.sql).
--                 rider_id is the phone number and is what delivery_dispatch / delivery_inflight / thread.recipient store.
--                 channel picks where messages WE start go ('whatsapp' | 'telegram'; RiderMessenger in ordelo/rider_messaging/).
--                 tuid authorises (the Telegram person, from_user.id); tcid addresses (the chat). Both are written only by the
--                 t_rider_* functions (telegram/t_rider_onboarding.sql) after the rider shared their OWN phone number.
-- LIFECYCLE     Riders are added by (a) the web onboarding form (rider_registrations -> manual insert) or (b) the rider bot's
--                 /start for an unknown phone: t_rider_link() inserts status = 'inactive', town/vehicle_type 'TBD', then
--                 t_rider_set_profile() stores the chosen town and vehicle. An operator activates: status = 'active'.
--               Telegram link: t_rider_link() sets tuid/tcid/t_*/phone_verified and channel = 'telegram' (and is_in_shift = true
--                 once, for an existing rider); a later contact share by a different Telegram account MOVES the link (D42).
--               is_in_shift: WhatsApp riders: reset to false every day by the shift enquiry, back to true on 'yes'.
-- CALLED BY     rider_master:
--                 sql       delivery_inflight_whook(), enquire_shift_availability(), fake_delivery_dispatch_whook()
--                           get_available_riders(), get_rider_payout_report(), job_rider_pickup_alerts()
--                           t_receipt_snapshot()
--                           t_rider_link(), t_rider_set_profile(), t_rider_choices(), t_rider_profile()
--                 python    utils_common/notify/restaurant_notifier.py (module-level SQL)
--                 python    utils_common/waba_utils/wa_senders.py: notify_ops_rider_alert(), notify_rest_admins_rider_alert()
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/on_callback_wa_handler.py: handle_shift_availability()
--                 python    watomation/on_message_wa_handler.py: process_wa_msg()
--                 python    watomation/routers/delivery_hooks.py: delivery_inflight_graph_init_hook(), shift_availability_enquiry_hook()
--                 python    watomation/routers/rider_auth_session.py: _resolve_rider_id()
--                 python    watomation/routers/sys_admin_auth_session.py: get_rider_payout()
--                 python    ordelo/rider_messaging/factory.py: for_rider() (channel, tcid)
--                 frontend  restaurant-frontend/app/api/sys-admin/rider-payouts/summary/route.ts
--                 frontend  restaurant-frontend/app/rider/more/page.tsx
--                 frontend  restaurant-frontend/app/sys-admin/riders-inshift/page.tsx
-- PYTHON MODEL  none
-- SECURITY      rider_master: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/regressions/test_p7_msg_handler.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/sql/test_rider_onboarding_sql.py
--               tests/utils_common/test_restaurant_notifier.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       rider_id is NOT NULL and UNIQUE only since migrations/rider_telegram_r1.sql (2026-10-22); older copies of this table
--                 (other environments) may still have duplicates or NULLs: run that migration's pre-checks there first.
--               Read with the anon key by restaurant-frontend and RLS is off, so tuid/tcid are readable by anon too: see
--                 docs/to-do.md (security review). The Telegram columns are written only through the service-role t_rider_*
--                 functions, but nothing stops a direct anon write while RLS is off.
--               status has no CHECK: dispatch now requires exactly 'active' (case-sensitive). The migration pre-check prints
--                 the live status values so no existing rider is cut off by spelling.
-- SEE ALSO      dispatch/job_create_dispatch.sql (get_available_riders)
--               dispatch/enquire_shift_availability.sql
--               core/rider_registrations.sql
--               telegram/t_rider_onboarding.sql
--               availability/pauses.sql
--               migrations/rider_telegram_r1.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table rider_master
--   Riders that can be offered delivery jobs, keyed by rider_id (their phone number, digits only).
--   status = 'active' + is_in_shift = true + matching town and vehicle (+ no open pause) makes a rider dispatchable;
--   status = 'active' also decides who gets the daily WhatsApp shift question; priority orders the offers (lower first);
--   shift_response_dtts is the last shift update. channel = where messages we start go; tuid/tcid = the Telegram link.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rider_master (
    id serial NOT NULL,
    rider_id character varying(12) NOT NULL, -- phone number, digits only (e.g. 447448440754); the rider's key everywhere
    rider_name text NOT NULL,
    vehicle_type character varying(15) NOT NULL, -- 'TBD' until a Telegram sign-up picks one
    town character varying(255) NOT NULL, -- 'TBD' until a Telegram sign-up picks one
    status character varying(50) NOT NULL, -- 'active' is dispatchable; Telegram sign-ups start 'inactive'
    is_in_shift boolean NOT NULL DEFAULT TRUE,
    priority integer NOT NULL DEFAULT 1,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_response_dtts timestamp without time zone,
    channel text NOT NULL DEFAULT 'whatsapp'::text, -- where messages we start go: 'whatsapp' | 'telegram'
    tuid bigint, -- Telegram user id (from_user.id): AUTHORISES; NULL = not linked
    tcid bigint, -- Telegram chat id: where the rider bot sends; NULL = not linked
    t_username text, -- @handle at the last link/refresh; display only, can change
    t_first_name text, -- Telegram first name at the last link/refresh; display only
    t_linked_at timestamp with time zone, -- when tuid was (re)linked
    phone_verified boolean NOT NULL DEFAULT FALSE, -- true once a Telegram contact share proved the phone belongs to tuid
    CONSTRAINT rider_master_pkey PRIMARY KEY (id),
    CONSTRAINT rider_master_rider_id_key UNIQUE (rider_id),
    CONSTRAINT rider_master_channel_check CHECK ((channel = ANY (ARRAY['whatsapp'::text, 'telegram'::text]))),
    CONSTRAINT rider_master_tg_link_complete CHECK (((tuid IS NULL) = (tcid IS NULL)))
);

-- One Telegram account maps to at most one rider (D42: a second rider row asking for the same tuid is refused).
CREATE UNIQUE INDEX IF NOT EXISTS rider_master_tuid_uidx ON public.rider_master USING btree (tuid)
WHERE (tuid IS NOT NULL);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.rider_master IS 'Riders that can be offered delivery jobs, keyed by rider_id (their phone number, digits only).';

COMMENT ON COLUMN public.rider_master.is_in_shift IS 'true when the rider said they are working today; required for dispatch';

COMMENT ON COLUMN public.rider_master.channel IS 'where messages we start go: whatsapp | telegram';

COMMENT ON COLUMN public.rider_master.tuid IS 'Telegram user id (from_user.id); authorises rider bot actions; NULL = not linked';

COMMENT ON COLUMN public.rider_master.tcid IS 'Telegram chat id the rider bot sends to; NULL = not linked';

COMMENT ON COLUMN public.rider_master.phone_verified IS 'true once a Telegram contact share proved this phone belongs to tuid';


-- ------------------------
select * from public.rider_master where rider_id = '447448440754';
delete from public.rider_master where rider_id = '447448440754';

