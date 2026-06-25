select * from delivery_dispatch; 


with riderMaster AS (
    select rider_id, rider_name, vehicle_type from rider_master
), riderRegistration AS (
    select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id, bank_account_name, sort_code, bank_account from rider_registrations
)
select 
-- r.rider_id, 
-- r.rider_name, 
-- r.vehicle_type, 
rr.bank_account_name, 
rr.sort_code, 
rr.bank_account, 
d.order_number, 
d.rider_payout,
-- d.rider_payout + 2 as adjusted_payout,
d.dtts
-- dOption.breakdown 
from delivery_dispatch d
join riderMaster r on d.rider_id = r.rider_id
join riderRegistration rr on r.rider_id = rr.rider_id
join delivery_option dOption on d.order_number = dOption.order_number and dOption.vehicle_type = r.vehicle_type
where d.status='completed' and d.rider_id !='447448440754' 
and d.dtts >= '2026-06-15' and d.dtts <= date('2026-06-23');
ORDER BY d.dtts DESC;

-- Aggregated view
with riderMaster AS (
    select rider_id, rider_name, vehicle_type from rider_master
), riderRegistration AS (
    select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id, bank_account_name, sort_code, bank_account from rider_registrations
)
select 
rr.bank_account_name, 
rr.sort_code, 
rr.bank_account, 
SUM(d.rider_payout) as rider_payout,
COUNT(DISTINCT d.order_number) as order_count
from delivery_dispatch d
join riderMaster r on d.rider_id = r.rider_id
join riderRegistration rr on r.rider_id = rr.rider_id
join delivery_option dOption on d.order_number = dOption.order_number and dOption.vehicle_type = r.vehicle_type
where d.status='completed' and d.rider_id !='447448440754'
and d.dtts >= '2026-05-24' and d.dtts <= date('2026-06-01')
group by rr.bank_account_name, rr.sort_code, rr.bank_account;

select * from delivery_option where order_number='ELAS-UIIA-20';
select * from delivery_option where order_number='SFCS-SOAZ-22';
select * from delivery_dispatch where order_number='ELAS-UIIA-20';
select * from rider_master where rider_id='447927803163';
select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id, bank_account_name, sort_code, bank_account from rider_registrations where rider_id='447927803163';
select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id, bank_account_name, sort_code, bank_account from rider_registrations where lower(full_name) like '%muhib%';

select * from rider_registrations;
