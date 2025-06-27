select status,
	rest_confirmation_code,
	cust_confirmation_code,
	current_timestamp - dtts as time_taken,
	*
from delivery_summary
order by dtts desc
limit 10;


select *
from delivery_detail
order by dtts desc
limit 10;


select *
from delivery_detail
order by dtts desc
limit 10;


select *
from ordelo_config;

SET http.timeout TO '15s';
SELECT public.process_delivery();


SELECT public.job_create_dispatch();


SELECT config_value 
FROM ordelo_config
WHERE config_key = 'ORDELO_APP_URL';