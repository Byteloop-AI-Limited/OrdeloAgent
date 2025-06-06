select init_delivery('447448440754', 'WREN-test-123');


select status,
       rest_confirmation_code,
       cust_confirmation_code,
       *
from delivery_summary
order by dtts desc;


select *
from delivery_detail
order by dtts desc;


select *
from delivery_inflight
order by dtts desc;


select *
from delivery_dispatch
order by dtts desc;


select *
from delivery_option
order by id desc;

-- Update delivery_detail

update delivery_detail
set status='vehicle_type_timedout'
where rider_id='447448440754';


select *
from