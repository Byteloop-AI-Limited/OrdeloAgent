select * from delivery_option;
select * from delivery_option;

select * from delivery_summary where status='completed' and rest_ref='ELAS';

select * from delivery_dispatch where status='completed';

select * from delivery_dispatch where status='completed' and rider_id !='447448440754';


select * from delivery_option where order_number='ELAS-DACF-20';
select * from delivery_option where order_number='ELAS-ZSLI-22';