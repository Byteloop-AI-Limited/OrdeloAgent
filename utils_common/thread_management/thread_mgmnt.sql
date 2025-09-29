CREATE TABLE public.thread (
  thread_id text NOT NULL,
  recipient character varying(255) NOT NULL,
  thread_ts timestamp without time zone NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
);