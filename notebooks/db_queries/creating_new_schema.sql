create schema if not exists elas;


grant usage on schema elas to anon, authenticated, service_role;

grant all on all tables in schema elas to anon, authenticated, service_role;
grant all on all routines in schema elas to anon, authenticated, service_role;
grant all on all sequences in schema elas to anon, authenticated, service_role;

alter default privileges for role postgres in schema elas
grant all on tables to anon, authenticated, service_role;

alter default privileges for role postgres in schema elas
grant all on routines to anon, authenticated, service_role;

alter default privileges for role postgres in schema elas
grant all on sequences to anon, authenticated, service_role;


create table elas.thread (
    thread_id text,
    recipient varchar(12),
    is_active boolean,
    retain_thread boolean default false,
    dt date default current_date,
    dtts timestamp default current_timestamp,
    last_access_dtts timestamp default current_timestamp,
    CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
);

-- On supabase dashboard, go to settings, data api,exposed schema, add elas