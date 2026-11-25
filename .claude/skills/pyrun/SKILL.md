---
name: pyrun
description: Run short Python snippets in the OrdeloAgent repo for calculations, inspecting settings or application state, calling a helper, or reproducing behaviour. For any database read or write, including table lookups and ordelo_config values, use the database-operations skill instead.
---

# Pyrun

Use this skill to run short, purpose-built Python snippets in the repo to answer a specific
question or inspect application state. Favor reusing existing imports,
utilities, and helper functions from nearby modules so the snippet stays minimal.

## Workflow

1. **Identify the minimal imports** needed for the query.
   - Prefer imports from the most relevant module that already encapsulates the logic.
   - Reuse constants, helper functions, and client instances.
   - Avoid rewriting logic inline; assemble existing pieces.

2. **Prepare the shell, then run the snippet** (see `docs/local-testing-runbook.md`; repeat in each new shell):
   ```sh
   source .venv/bin/activate && export PYTHONPATH="$PWD" && envLoad
   python - <<'PY'
   # your code here
   PY
   ```

3. **If imports fail (ModuleNotFoundError)**, run bootstrap installer first:
   ```sh
   uv pip install \
     pydantic-settings boto3 loguru supabase "pywa==3.6.1" \
     "pandas==2.2.3" gspread "duckdb==1.4.3" \
     "psycopg[binary]" psycopg-pool \
     "langchain==1.2.15" "langchain-openai==1.1.14" \
     "langgraph==1.1.5" "langgraph-checkpoint-postgres==3.0.5" \
     -q
   ```
   Then retry. If that fails, run `./run_setup.sh` to create or sync the venv and prepare the shell again.

4. **Keep snippets focused** — treat each pyrun like a Jupyter cell: short, focused, iterative.

---

## Standard Imports & Clients

### Database

Use the database-operations skill. `client_ordelo` is a service-role client that bypasses RLS, so do not use it
for ad-hoc queries here.

### Config & Settings

```python
from config import project_settings, waba_setting

# Check webhook
business_phone = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone.webhook_configuration)
```

### Utilities

```python
from utils_common.thread_management.thread_handler import ThreadHandler
```

---

## General Examples

### Check Webhook Config

```python
from config import waba_setting

business_phone = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone.webhook_configuration)
```

### Inspect Project Settings

```python
from config import project_settings

print(f"REST Ref: {project_settings.rest_ref}")
print(f"Project Root: {project_settings.project_root}")
```

### Debug Thread Messages

```python
import asyncio
from ordelo.agents.agent_runner import debug_thread

state = asyncio.run(debug_thread("some_thread_id"))
print(state.get("messages", []))
```

---

## Environment Notes

- **Python version**: `pyproject.toml` requires `>=3.11`; the repo `.venv` is Python 3.13.

- **Run `./run_setup.sh`, don't source it** — it uses `set -euo pipefail`, which would change your shell.

---

## Iterative Development

Treat each pyrun call like a Jupyter cell:
1. Run a small snippet to verify the imports work
2. Expand the query based on what you learn
3. Print intermediate results to debug
4. Refine as needed

Don't try to write complex multi-function scripts in one shot — iterate.
