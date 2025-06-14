
delete
from delivery_option
where order_number like 'WREN-TEST%';


delete
from delivery_option
where order_number like 'WREN-TEST-%'
    and order_number != 'WREN-TEST-01';


delete
from delivery_pricing_detail
where order_number like 'WREN-TEST-%';


delete
from delivery_summary
where order_number like 'WREN-TEST%';


delete
from delivery_detail
where order_number like 'WREN-TEST%';


delete
from delivery_dispatch
where order_number like 'WREN-TEST%';


delete
from delivery_inflight
where order_number like 'WREN-TEST%';


delete
from delivery_dispatch
where order_number like 'WREN-TEST%';


select *
from delivery_option
limit 100;

-- update order_number ELAB-KHEB-45 to WREN-TEST-01 FOR DELIVERY_option and delivery_pricing_detail
 -- update delivery_pricing_detail
-- set order_number = 'WREN-TEST-01'
-- where order_number = 'QPRX-21';

update delivery_option
set order_number = 'WREN-TEST-01'
where order_number = 'QPRX-21';

-- Inserting a test record required by /test to update.
