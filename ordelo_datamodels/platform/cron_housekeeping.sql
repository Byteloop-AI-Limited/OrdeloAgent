-- pg_cron job 'delete-job-run-details' (live schedule: 0 12 * * *, active). cron.schedule() updates the job in place when the name already exists.
SELECT
    cron.schedule ('delete-job-run-details', '0 12 * * *', 'DELETE FROM cron.job_run_details WHERE end_time < now() - interval ''1 day''');
