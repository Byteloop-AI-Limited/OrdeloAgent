CREATE TABLE IF NOT EXISTS public.web_monitor_run (
    run_day date NOT NULL,
    completed_at timestamp with time zone,
    alert_orders text[] NOT NULL DEFAULT '{}' ::text[],
    CONSTRAINT web_monitor_run_pkey PRIMARY KEY (run_day)
);

ALTER TABLE public.web_monitor_run ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_monitor_run FROM anon, authenticated;
