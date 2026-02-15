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

## Setup and Execution

### Using run_setup.sh (Recommended)

The project provides `run_setup.sh` which handles venv activation and PYTHONPATH setup:

```bash
./run_setup.sh  # First time setup (requires AWS_SETTINGS_* env vars)
source .venv/bin/activate  # Subsequent runs - PYTHONPATH is auto-set
```

**Note:** AWS_SETTINGS_* environment variables must be set by the cloud environment:
- `AWS_SETTINGS_KEY_ID`
- `AWS_SETTINGS_ACCESS_KEY`
- `AWS_SETTINGS_REGION`
- `AWS_SETTINGS_SECRET_NAME`

### Running the Script

```bash
# Check only (prod mode)
python notebooks/prod_deployment_checker.py --mode prod

# Apply updates (prod mode)
python notebooks/prod_deployment_checker.py --mode prod --apply

# Skip WABA webhook check
python notebooks/prod_deployment_checker.py --mode prod --skip-waba
```

### Full Command Example

```bash
source .venv/bin/activate && python notebooks/prod_deployment_checker.py --mode prod
```

## Important

- **Never skip any step** (e.g. `--skip-waba`) unless the user explicitly asks to skip it. Always apply all steps by default.

## Checklist script notes

- DB updates use `client_ordelo` from `config/pg_setting.py`.
- WABA updates use `_sync_wa_client` and `waba_business_settings` from `config/waba_setting.py`.
- For running Python snippets or if you need env/venv setup, follow `.codex/skills/pyrun/SKILL.md`.
- If Supabase or WABA calls need network access, rerun with escalated permissions.

## Step mapping

- Step1: `restaurant_master` updates from `notebooks/db_queries/rest_master_updates.sql` lines 10-24.
- Step2: `rider_master` updates from `notebooks/db_queries/rider_master_updates.sql` lines 14-21.
- Step3: `ordelo_config` `ORDELO_APP_URL` update from `notebooks/db_queries/config_updates.sql` line 5 (test) or line 14 (prod).
- Step4: WABA webhook update from `config/waba_setting.py` lines 123-131.
