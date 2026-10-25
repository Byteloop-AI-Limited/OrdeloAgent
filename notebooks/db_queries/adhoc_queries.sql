select * from public.pauses;
update public.pauses set ends_at = now() + interval '1 minute' where ends_at > now();

select * from public.restaurant_admin;
select * from public.admin_roster;
select * from rider_master where rider_id in ('447448440754', '447446933210') order by is_in_shift desc, shift_response_dtts desc, status asc;


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