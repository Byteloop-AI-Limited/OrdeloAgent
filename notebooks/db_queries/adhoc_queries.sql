select * from public.pauses;
update public.pauses set ends_at = now() + interval '1 minute' where ends_at > now();


select * from rider_master where rider_id in ('447448440754', '447446933210') order by is_in_shift desc, shift_response_dtts desc, status asc;