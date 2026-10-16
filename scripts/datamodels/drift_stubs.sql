-- Throwaway-database stand-ins for Supabase roles and extensions that are not installable here.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_cron;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
-- pg_net
CREATE SCHEMA IF NOT EXISTS net;
CREATE OR REPLACE FUNCTION net.http_post(url text, body jsonb DEFAULT '{}'::jsonb, params jsonb DEFAULT '{}'::jsonb,
  headers jsonb DEFAULT '{"Content-Type": "application/json"}'::jsonb, timeout_milliseconds integer DEFAULT 5000)
  RETURNS bigint LANGUAGE sql AS $f$ SELECT 1::bigint $f$;
-- pgsql-http (installed in public on live)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='http_header') THEN CREATE TYPE public.http_header AS (field varchar, value varchar); END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='http_response') THEN
    CREATE TYPE public.http_response AS (status integer, content_type varchar, headers public.http_header[], content varchar); END IF;
END $$;
CREATE OR REPLACE FUNCTION public.http_post(uri varchar, content varchar, content_type varchar) RETURNS public.http_response
  LANGUAGE sql AS $f$ SELECT ROW(200, 'application/json', ARRAY[]::public.http_header[], '{}')::public.http_response $f$;
CREATE OR REPLACE FUNCTION public.http_post(uri varchar, data jsonb) RETURNS public.http_response
  LANGUAGE sql AS $f$ SELECT ROW(200, 'application/json', ARRAY[]::public.http_header[], '{}')::public.http_response $f$;
CREATE OR REPLACE FUNCTION public.http_header(field varchar, value varchar) RETURNS public.http_header
  LANGUAGE sql AS $f$ SELECT ROW(field, value)::public.http_header $f$;
-- pgmq
CREATE SCHEMA IF NOT EXISTS pgmq;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='pgmq' AND typname='message_record') THEN
    CREATE TYPE pgmq.message_record AS (msg_id bigint, read_ct integer, enqueued_at timestamptz, vt timestamptz, message jsonb); END IF;
END $$;
CREATE OR REPLACE FUNCTION pgmq.read(queue_name text, vt integer, qty integer) RETURNS SETOF pgmq.message_record LANGUAGE sql AS $f$ SELECT NULL::pgmq.message_record WHERE false $f$;
CREATE OR REPLACE FUNCTION pgmq.archive(queue_name text, msg_id bigint) RETURNS boolean LANGUAGE sql AS $f$ SELECT true $f$;
CREATE OR REPLACE FUNCTION pgmq.delete(queue_name text, msg_id bigint) RETURNS boolean LANGUAGE sql AS $f$ SELECT true $f$;
