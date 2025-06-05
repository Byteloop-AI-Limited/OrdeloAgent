-- Setup test values
delete from delivery_dispatch where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3');

INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, status) VALUES 
('0f9d9e9b75fa4db7a1e34e0c53c6b986', '447448440754', 5.00, 1.5, 'accepted'), -- assigned
('0f9d9e9b75fa4db7a1e34e0c53c6b986', '441234567891', 5.00, 1.5, 'accepted') -- missed
;

INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, status) VALUES 
('bfde0feadaee4d1fb660335d932c37f3', '447448440754', 5.00, 1.5, 'accepted'), -- this order status should still be unassigned
('bfde0feadaee4d1fb660335d932c37f3', '447448440754', 5.00, 1.5, 'accepted')
;

INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, status) VALUES 
('8bac3a27f6354abcb3466269a719e13a', '447448440754', 5.00, 1.5, 'accepted') -- This would remain unassigned because the only rider who accepted it was assigned the 
;
-- One of the above order will never be assigned
INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, status) VALUES 
('8bac3a27f6354abcb3466269a719e13a', '447424334783', 5.00, 1.5, 'accepted') -- This would remain unassigned because the only rider who accepted it was assigned the 
;
-- Verify
select status, dispatch_id, rider_id, order_number 
from delivery_detail 
where 
order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3') 
--and status='unassigned'
order by dtts desc;

select dispatch_id, order_number, rider_id, status, status_update_dtts  
from delivery_dispatch dd 
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3')
order by order_number, dispatch_id;

select * 
from delivery_inflight
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3')


-- run logic
--select assign_accepted_dispatch('0f9d9e9b75fa4db7a1e34e0c53c6b986');
--select assign_accepted_dispatch('8bac3a27f6354abcb3466269a719e13a');

-- Calling in bulk this should run every 5 seconds, if there is an order available
select 
	assign_accepted_dispatch(order_number),
	status, 
	dispatch_id, 
	rider_id, 
	order_number 
from delivery_detail 
where 
order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3')
and status='unassigned'
order by dtts asc;




--- Cleanup
-- setup for testing
update delivery_detail  
set status='unassigned', dispatch_id = null, rider_id = null
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3');

update delivery_dispatch
set status='accepted', status_update_dtts = Null
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3');

delete from delivery_inflight
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a', 'bfde0feadaee4d1fb660335d932c37f3');


-------


---------
select notify_missed_dispatches();
select notify_missed_dispatches_for_order('0f9d9e9b75fa4db7a1e34e0c53c6b986');
