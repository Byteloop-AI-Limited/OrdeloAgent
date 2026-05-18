-- Total number of deliveries
select count(*) as total_deliveries from delivery_dispatch d where d.status='completed' and d.rider_id !='447448440754' and d.order_number like 'ELA%';


-- Total number of takeaway orders
select count(*) as total_takeaway_orders from takeaway_summary where customer_id !='447448440754' and order_number like 'ELA%';

select * from delivery_summary limit 1;

-- Monthly deliveries
with spine as (
    select distinct order_number from delivery_dispatch d where d.status='completed' and d.rider_id !='447448440754' and d.order_number like 'ELA%'
)
select TO_CHAR(dt, 'YYYY-MM') AS month, count(*) as total_deliveries from delivery_summary where exists (select 1 from spine where spine.order_number = delivery_summary.order_number) group by TO_CHAR(dt, 'YYYY-MM') order by month;
2026-03	12
2025-12	11
2026-04	11
2026-01	10
2026-02	10
2026-05	7;

-- Monthly takeaway orders
with spine as (
    select distinct order_number from takeaway_summary where customer_id !='447448440754' and order_number like 'ELA%'
)
select TO_CHAR(dt, 'YYYY-MM') AS month, count(*) as total_takeaway_orders from takeaway_summary where exists (select 1 from spine where spine.order_number = takeaway_summary.order_number) group by TO_CHAR(dt, 'YYYY-MM') order by month;
2026-02	2
2026-03	8
2026-04	3
2026-05	5;

-- delivery value
with spine as (
    select distinct order_number from delivery_dispatch d where d.status='completed' and d.rider_id !='447448440754' and d.order_number like 'ELA%'
)
select TO_CHAR(order_dt, 'YYYY-MM') as month, sum(total_price) as total_delivery_value, avg(total_price) as avg_delivery_value from food_order where exists (select 1 from spine where spine.order_number = food_order.order_number) group by TO_CHAR(order_dt, 'YYYY-MM');
2025-12	680.24	61.84
2026-01	310.88	31.088
2026-02	331.24	33.124
2026-03	403.12	33.5933333333333
2026-04	452.88	41.1709090909091
2026-05	204.88	29.2685714285714;
[]