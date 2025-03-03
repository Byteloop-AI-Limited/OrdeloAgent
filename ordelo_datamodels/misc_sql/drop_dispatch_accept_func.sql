-- SQL script to drop all functions named 'dispatch_accept_func' regardless of arguments
DO $$
DECLARE
    func_record RECORD;
BEGIN
    FOR func_record IN 
        SELECT n.nspname AS schema_name, p.proname, pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.proname = 'dispatch_accept_func'
    LOOP
        EXECUTE format('DROP FUNCTION %I.%I(%s);', 
                      func_record.schema_name, 
                      func_record.proname, 
                      func_record.args);
        RAISE NOTICE 'Dropped function %I.%I(%s)', 
                     func_record.schema_name, 
                     func_record.proname, 
                     func_record.args;
    END LOOP;
END;
$$;
