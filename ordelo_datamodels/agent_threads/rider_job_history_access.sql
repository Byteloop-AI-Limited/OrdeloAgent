-- =============================================================================================
-- ordelo_datamodels/agent_threads/rider_job_history_access.sql
-- Restrict direct access to external thread and checkpoint history containing rider job details.
-- =============================================================================================
-- LIVE CHECK    Anonymous reads verified open on all four tables read-only 2026-10-26; restrictions not applied.
-- OBJECTS       alter  thread
--                   Server-only access to the restaurant-agent-owned conversation index.
--               alter  checkpoints
--                   Server-only access to LangGraph checkpoint metadata.
--               alter  checkpoint_blobs
--                   Server-only access to serialized LangGraph state.
--               alter  checkpoint_writes
--                   Server-only access to pending LangGraph writes.
-- REQUIRES      restaurant-agents: thread; LangGraph checkpoint installation: checkpoints, checkpoint_blobs, checkpoint_writes
-- HOW TO RUN    Included by scripts/datamodels/rider_dashboard_cutover.py; owner applies during maintenance.
-- SIDE EFFECTS  Revokes direct public access; does not change library DDL, histories or graph behavior.
-- HOW IT FITS   Securing the jobs view must not leave the same private details readable through graph storage.
-- LIFECYCLE     No rows are created, removed or repaired. Existing server/DB-pool graph access continues.
-- CALLED BY     scripts/datamodels/rider_dashboard_cutover.py (manual SQL generation only)
-- PYTHON MODEL  none
-- SECURITY      RLS on; no PUBLIC/anon/authenticated grants; explicit server-role grants.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
-- GOTCHAS       These objects are owned externally. This file changes access only, never copies their definitions.
-- SEE ALSO      agent_threads/rider_threads.sql
-- =============================================================================================

-- The external index and library checkpoint tables can contain the same jobs/customer details as dispatches.
-- Restrict their direct access without redefining their schema or replacing LangGraph persistence.
ALTER TABLE public.thread ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoints ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoint_blobs ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.checkpoint_writes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.thread, public.checkpoints, public.checkpoint_blobs, public.checkpoint_writes FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.thread, public.checkpoints, public.checkpoint_blobs, public.checkpoint_writes TO service_role;
