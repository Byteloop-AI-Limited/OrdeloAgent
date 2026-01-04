---
name: pyrun
description: Execute small Python snippets in this repo to answer ad-hoc questions or inspect live configuration/state (e.g., fetching webhook_configuration). Use when the user asks to run Python code or queries that require running Python in the project context.
---

# Pyrun

Use this skill to run short, purpose-built Python snippets in the repo to answer a specific question.

## Workflow

1) Identify the minimal imports and objects needed for the query.
2) Assume the environment is already set up via `run_setup.sh`. Just activate the venv:

```sh
source .venv/bin/activate  # PYTHONPATH is automatically set
```

If .venv doesn't exist or fails, run the setup script first:

```sh
./run_setup.sh
```

**Note:** AWS_SETTINGS_* environment variables must be set (handled by cloud environment). The setup script validates these are present.

3) Write a tiny script using a `python - <<'PY'` heredoc; run from the repo root.
4) If the code needs network (e.g., AWS Secrets Manager, Supabase, external APIs), rerun with `sandbox_permissions: require_escalated`.
5) Print only the required fields; avoid dumping secrets.

## Example

```py
from config import waba_setting

business_phone_number = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone_number.webhook_configuration)
```

## Reference scripts

- `scripts/debug_thread_messages.py` prints only the message content for a given thread_id using `debug_thread`.
