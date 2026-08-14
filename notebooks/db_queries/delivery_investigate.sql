-- order_number: ELAS-JEJK-20 
-- rider_id: 447427558868
-- dispatch_id=1036
select * from delivery_summary where order_number='ELAS-JEJK-20' order by dtts desc;
-- update status='timedout' for order_number='ELAS-JEJK-20'
update delivery_summary set status='timedout' where order_number='ELAS-JEJK-20';

select * from delivery_dispatch where order_number='BNAT-VNXL-21' order by dtts desc;
update delivery_dispatch set status='unassigned' where order_number='ELAS-JEJK-20';
-- 2026-08-12T20:10:42.914Z - Look for logs around this time
-- https://eu-west-2.console.aws.amazon.com/cloudwatch/home?region=eu-west-2#logsV2:log-groups/log-group/$252Faws$252Fapprunner$252FOrdeloAgentRunner$252F623a4467a103486390040f64d6ca9574$252Fapplication/log-events/instance$252F1d075f1c92cf4774b01d5499fe81f7b4$3Fstart$3D-86400000
-- 

select * from delivery_summary where order_number like '%SFCS%' order by dtts desc;

select * from delivery_detail where order_number = 'ELAS-JEJK-20';
update delivery_detail set status='vehicle_type_timedout' where order_number='ELAS-JEJK-20';

select * from delivery_inflight;
