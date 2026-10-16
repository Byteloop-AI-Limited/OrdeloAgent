-- =============================================================================================
-- ordelo_datamodels/platform/cron_housekeeping.sql
-- pg_cron housekeeping: delete cron run history older than a day.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       none
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Daily DELETE on cron.job_run_details.
-- HOW IT FITS   cron.job_run_details grows by one row per job run (about 100,000 rows a day with the 5- and 10-second jobs). This job,
--                 daily at 12:00 UTC, deletes rows older than one day.
-- LIFECYCLE     none
-- CALLED BY     none
-- PYTHON MODEL  none
-- SECURITY      none
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      every job_*.sql file (their cron statements)
-- =============================================================================================

-- pg_cron job 'delete-job-run-details': runs every 0 12 * * *, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('delete-job-run-details', '0 12 * * *', 'DELETE FROM cron.job_run_details WHERE end_time < now() - interval ''1 day''');
