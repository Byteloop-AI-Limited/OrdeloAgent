---
name: prod-deployment-checker
description: Check and switch the Ordelo app between test and production by running the deployment checklist and applying DB/WABA updates (restaurant_master, rider_master, ordelo_config, WABA webhook). Use when verifying prod readiness or toggling test/prod mode via client_ordelo and waba_setting.
---

# Prod Deployment Checker

Use this skill to verify the deployment checklist and switch between test/prod mode.

## Workflow

1) Choose the target mode: `test` or `prod`.
2) Run the checklist script from the repo root:
   - Check only: `python notebooks/prod_deployment_checker.py --mode <mode>`
   - Apply updates: `python notebooks/prod_deployment_checker.py --mode <mode> --apply`
3) Review the step outputs and resolve any mismatches.

## Checklist script notes

- DB updates use `client_ordelo` from `config/pg_setting.py`.
- WABA updates use `_sync_wa_client` and `waba_business_settings` from `config/waba_setting.py`.
- The WABA callback verification expects the webhook URL to respond; ensure the local server is running before applying WABA updates.
- For running Python snippets or if you need env/venv setup, follow `.codex/skills/pyrun/SKILL.md`.
- If Supabase or WABA calls need network access, rerun with escalated permissions.

## Step mapping

- Step1: `restaurant_master` updates from `notebooks/db_queries/rest_master_updates.sql` lines 10-24.
- Step2: `rider_master` updates from `notebooks/db_queries/rider_master_updates.sql` lines 14-21.
- Step3: `ordelo_config` `ORDELO_APP_URL` update from `notebooks/db_queries/config_updates.sql` line 5 (test) or line 14 (prod).
- Step4: WABA webhook update from `config/waba_setting.py` lines 123-131.
