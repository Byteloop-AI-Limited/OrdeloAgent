-- CREATE TABLE public.thread (
--   thread_id text NOT NULL,
--   from_number character varying(255) NOT NULL,
--   thread_ts timestamp without time zone NOT NULL,
--   is_active boolean NOT NULL DEFAULT true,
--   CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
-- );

create table public.thread (
    thread_id text,
    from_number varchar(12),
    is_active boolean,
    dt date default current_date,
    dtts timestamp default current_timestamp,
    CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
);