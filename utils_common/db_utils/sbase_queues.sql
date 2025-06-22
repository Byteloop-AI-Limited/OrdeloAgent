-- https://supabase.com/blog/supabase-queues#from-the-client
-- https://supabase.com/docs/guides/api/using-custom-schemas
-- step 1on queue, go to create police, select all to anon and authenticated.
-- step2 - go to queue settings and toggle the permissions
-- step 3 - run below
GRANT USAGE ON SCHEMA pgmq_public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA pgmq_public TO anon, authenticated, service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA pgmq_public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA pgmq_public TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA pgmq_public GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA pgmq_public GRANT ALL ON ROUTINES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA pgmq_public GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
