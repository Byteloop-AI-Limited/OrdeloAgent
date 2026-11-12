select rider_id, channel,* from rider_master order by channel;
select * from public.pauses;
update public.pauses set ends_at = now() + interval '1 minute' where ends_at > now();

select * from public.restaurant_admin;
select * from public.admin_roster;
select * from rider_master where rider_id in ('447448440754', '447446933210') order by is_in_shift desc, shift_response_dtts desc, status asc;

select * from rider_master;
  SELECT rider_id, rider_name, status, is_in_shift, town, vehicle_type, priority,
          public.is_paused('rider', rider_id, NULL) AS paused,
          rider_id IN (SELECT btrim(x) FROM ordelo_config oc,
                       regexp_split_to_table(oc.config_value, ',') x
                       WHERE oc.config_key = 'overwatch_list') AS in_overwatch,
          EXISTS (SELECT 1 FROM delivery_inflight i WHERE i.rider_id = rider_master.rider_id) AS on_job
   FROM rider_master
   WHERE rider_name IN ('lohith', 'lohithNwg');
 
   SELECT order_number, public.order_has_test_item(order_number) AS is_test
   FROM delivery_detail WHERE order_number LIKE 'STRK-TEST-%';


select * from ordelo_config where config_key like 'overwatch_list';

UPDATE public.t_invites SET status = 'revoked'
WHERE status = 'claimed' AND rest_ref = 'STRK'
  AND public.admin_phone_digits(phone_number) IN ('447448440754','447929843965')
RETURNING invite_code, phone_number;

UPDATE public.t_invites SET status = 'revoked'
WHERE status = 'claimed' AND rest_ref = 'STRK'
  AND public.admin_phone_digits(phone_number) IN ('447448440754','447929843965')
RETURNING invite_code, phone_number;

DELETE FROM public.restaurant_admin WHERE phone IN ('447448440754','447929843965');
SELECT public.admin_unlink_telegram('447448440754', 'test');
SELECT public.admin_unlink_telegram('447929843965', 'test');
SELECT phone, tuid, channels FROM public.restaurant_admin
WHERE phone IN ('447448440754','447929843965'); 
select * from public.restaurant_admin;


-- 1. The full record. tcid must be set (it should equal your Telegram chat id).
SELECT phone, tuid, tcid, channels, t_first_name FROM public.restaurant_admin WHERE phone = '447929843965';

-- 2. Is the number on STRK's list, and is it paused?
SELECT phone, channels, tcid FROM public.admin_roster WHERE rest_ref = 'ELAS';
SELECT public.is_paused('rest_admin', '447929843965', 'STRK') AS paused;

-- 3. Where alerts would go. Cards use #3a; new notices use #3b.
SELECT * FROM public.t_order_card_destinations('rest_admin', 'STRK');   -- 3a
SELECT * FROM public.t_alert_destinations('rest_admin', 'STRK');       -- 3b

-- 4. Are the migrated functions the live ones?
SELECT proname, prosrc LIKE '%admin_roster%' AS uses_roster
FROM pg_proc WHERE proname IN ('t_order_card_destinations','t_alert_destinations');

-- 5. Did the test order produce a card, and was it sent?
SELECT * FROM public.t_order_alerts ORDER BY 1 DESC LIMIT 3;
SELECT * FROM public.t_sent_messages ORDER BY 1 DESC LIMIT 5;
SELECT prosrc LIKE '%restaurant_admin%' FROM pg_proc WHERE proname = 't_alert_destinations';  -- true

SELECT proname FROM pg_proc
WHERE proname IN ('t_admin_restaurants','t_order_admin_phone','restaurant_admin_label','admin_for_tuid');
-- expect 4 rows

SELECT prosrc LIKE '%admin_for_tuid%' AS uses_roster FROM pg_proc WHERE proname = 't_order_admin_phone';
-- expect true

SELECT prosrc LIKE '%restaurant_admin%' AS uses_record FROM pg_proc WHERE proname = 't_alert_destinations';
-- expect true

SELECT * FROM public.t_order_card_destinations('rest_admin','STRK');
SELECT * FROM public.t_alert_destinations('rest_admin','STRK');
-- expect your linked number, with its tcid, in both


SELECT dispatch_id, rider_id, status, channel, dtts, status_update_dtts
  FROM delivery_dispatch WHERE order_number = 'STRK-TEST-004731' ORDER BY dispatch_id;
SELECT status FROM delivery_summary WHERE order_number = 'STRK-TEST-004731';           -- expect unassigned
SELECT vehicle_type, status FROM delivery_detail WHERE order_number = 'STRK-TEST-004731'; -- expect vehicle_type_timedout
SELECT kind, dispatch_id, offset_secs, status, swept_at
  FROM rider_offer_alert WHERE order_number = 'STRK-TEST-004731' ORDER BY kind, dispatch_id, offset_secs;
  
  select * from ordelo_config where config_key like 'STRK_TGRAM_ORDER_ALERT_OFFSETS_SECS%';
