select * from delivery_option where order_number = 'WREN-RFZX-21';

delete
from delivery_option
where order_number like 'WREN-TEST%';
    and order_number != 'WREN-TEST-01';

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



select *
from delivery_option
limit 100;

-- Insert a sample test that will continue to be updated later on, with subsequent tests.
insert into delivery_pricing_detail(order_number, distance, message)
values('WREN-TEST-02', 0.83, 'Test message');

update delivery_option
set order_number = 'WREN-TEST-02'
where order_number = 'WREN-RFZX-21';

-- Inserting a test record required by /test to update.
