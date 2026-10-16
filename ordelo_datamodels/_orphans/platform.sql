CREATE TABLE IF NOT EXISTS public.sbase_test_realtime (
    id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    column1 text NOT NULL,
    column2 text NOT NULL,
    CONSTRAINT sbase_test_realtime_pkey PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.rec (
    msg_id bigint,
    read_ct integer,
    enqueued_at timestamp with time zone,
    vt timestamp with time zone,
    message jsonb
);

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
CREATE OR REPLACE FUNCTION public.notify_http_endpoint()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  response json;
BEGIN
  -- Make the HTTP POST request to the specified endpoint
  response := (SELECT content FROM http_post('https://live-track.byteloop.ai/test-sbase', 
    json_build_object('old', row_to_json(OLD), 'new', row_to_json(NEW))::text, 
    'application/json'));

  -- Optionally, you can log the response or handle it as needed
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS trigger_notify_http ON public.sbase_test_realtime;
CREATE TRIGGER trigger_notify_http AFTER INSERT OR UPDATE ON sbase_test_realtime FOR EACH ROW EXECUTE FUNCTION notify_http_endpoint();
