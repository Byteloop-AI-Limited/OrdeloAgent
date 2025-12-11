-- Master data maintenance for restaurant_master, rider_master, and customer_master.
-- Consolidated from CommonQueries.sql and config_updates.sql.

-- Restaurant master checks and updates
select * from restaurant_master where rest_ref='WREN';
select * from restaurant_master where rest_ref = 'ELAS';
-- ELAS 51.0726635283769	-1.79717268758398
-- WREN 51.3601711280004	0.0907554051501591
update restaurant_master set lat = 51.3601711280004, lon = 0.0907554051501591 where rest_ref = 'ELAS';

update restaurant_master
-- set admins = array[ '447446933210', '447919202938']
set admins = array['447919202938']
where rest_ref = 'ELAS';

update restaurant_master
set admins = array[ '447424334783', '447919202938']
where rest_ref = 'WREN';



update restaurant_master
set admins = array['447424334783']
where rest_ref = 'ELAS';

update restaurant_master
set admins = array['447919202938']
where rest_ref = 'ELAS';

update restaurant_master
set lat = 51.359349, lon = 0.0904094
where rest_ref = 'WREN';

insert into restaurant_master (
    rest_ref,
    rest_id,
    rest_name,
    rest_email,
    admins,
    house_number,
    building_name,
    street_name,
    city,
    postcode,
    lat,
    lon
)
values (
    'ELAS',
    '447914844933',
    'Elai - Salisbury',
    null,
    array['447424334783', '447914844933'],
    'Mill Stream Approach',
    null,
    'Castle St',
    'Salisbury',
    'SP1 3TA',
    51.07266352837689,
    -1.797172687583984
);

-- Rider master checks and updates
select * from rider_master;
select * from rider_master where rider_id = '447448440754';
select * from rider_master where status = 'active' limit 10;

update rider_master
set is_in_shift = false;
-- where rider_name in ('Syama');

update rider_master
set town = 'Salisbury'
where rider_id in ('447448440754', '447446933210');

delete from rider_master
where rider_id in ('447448440754') and vehicle_type in ('electric_bike', 'scooter');

delete from rider_master
where rider_id = '447448440754' and vehicle_type = 'bicycle';

delete from rider_master
where id = 5;

-- Customer master (no statements found in source files; add here when available)
