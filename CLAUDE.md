# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OrdeloAgent is an AI-powered on-demand food delivery orchestration system. It uses WhatsApp Business API as the primary interface for riders, restaurants, and customers, with a FastAPI backend, LangGraph agents for stateful rider workflow management, and PostgreSQL (via Supabase) for persistence and business logic.

## Commands

Follow the [local testing runbook](docs/local-testing-runbook.md) to run OrdeloAgent and the sibling restaurant-frontend, expose them through Cloudflare Tunnel, and switch/restore shared `ordelo_config` URLs during maintenance. Before any Python command, activate `venv` (or `.venv`), set `PYTHONPATH="$PWD"`, and load `.env` using `envLoad` as documented there.

For aiogram bot changes, use the project [Telegram Vertification Loop skill](.claude/skills/telegram-vertification-loop/SKILL.md) to verify dispatcher, webhook, database, and live Telegram evidence.

```bash
# Dev server
uv run watomation/fapp_ordelo_agent.py  # port 3100; use --active with venv

# Production (Docker)
./start.sh  # gunicorn + uvicorn worker

# Tests
pytest                          # all tests
pytest tests/watomation/        # specific module
pytest tests/watomation/routers/test_delivery_hooks.py  # single file
pytest -k "test_name"           # single test by name

# Linting (ruff, F-rules only, F704 ignored)
ruff check .

# Dependencies (uses UV package manager)
uv sync
```

## Architecture

### Entry Point & Routing

The FastAPI app lives in `watomation/fapp_ordelo_agent.py`. It initializes the WhatsApp async client, registers message/callback/flow handlers, and includes routers:

- `watomation/routers/delivery_hooks.py` — delivery webhook endpoints (triggered by DB events)
- `watomation/routers/location_hooks.py` — live location tracking
- `watomation/routers/wa_location_hooks.py` — open on-demand rider-location requests
- `watomation/routers/takeaway_hooks.py` — takeaway restaurant flow
- `watomation/routers/order_hooks.py` — order management
- `watomation/routers/payment_hooks.py` — payment integration
- `watomation/routers/thread_hooks.py` — thread lifecycle

### Event-Driven Flow

PostgreSQL triggers fire webhook calls to FastAPI endpoints. Example: a `delivery_dispatch` INSERT trigger calls `/delivery-hooks/delivery-dispatch`. Handlers respond immediately and perform async work via FastAPI `BackgroundTasks`. Scheduled jobs run via `pg_cron`.

### LangGraph Rider Agent

The core agent is in `ordelo/agents/rider_agent.py`. It manages the inflight delivery workflow using a `StateGraph` with:

- **State** (`AgentState`): messages, dispatch_id, rider_name, confirmation codes, cancel state
- **Tools**: `send_delivery_instructions`, `verify_restaurant_confirmation_code`, `verify_customer_confirmation_code`, `cancel_delivery_before_pickup`, `terminate_delivery_job`
- **Nodes**: `agent_node` → `ToolNode` → `respond_node`
- **Persistence**: `AsyncPostgresSaver` (PostgreSQL checkpointer), thread-per-rider mapping

`ordelo/agents/agent_runner.py` contains helpers to invoke the graph (`run_rider_graph`), initialize state for new deliveries (`init_ordelo_graph`), and debug state (`debug_state`).

### WhatsApp Message Flow

```
WhatsApp current location → on_wa_location_handler.handle_wa_location_message()
  → WaLocation correlation and routing (only for a pending authorised request)

Other WhatsApp Message → on_message_wa_handler.process_wa_msg()
  → ThreadHandler.get_thread() (LangGraph thread lookup)
  → run_rider_agent_w_custom_msg(recipient, human_msg)
  → rider_agent graph invocation
  → WhatsApp response
```

- **Messages**: `watomation/on_message_wa_handler.py` — routes to rider agent or utility commands (`/test`, `/reset`, `/live`, `/flow`)
- **Callbacks**: `watomation/on_callback_wa_handler.py` — Accept/Decline dispatch, pickup time selection
- **Flows**: `watomation/on_flow_request_wa_handler.py` (customer address), `watomation/on_flow_request_postcode_search.py` (postcode)

### Delivery Lifecycle (6 Phases)

1. **Order Creation**: `init_delivery()` → status `restaurant_unconfirmed`
2. **Restaurant Confirmation**: Accept/Decline/Timeout → pickup time selection
3. **Dispatch Creation**: `process_delivery()` + `job_create_dispatch()` → riders notified
4. **Rider Assignment**: Accept/Decline → `job_assign_dispatch()` → status `assigned`
5. **Delivery Execution**: Inflight agent (instructions → tracking → verification codes)
6. **Completion**: `dispatch_complete_func()` → status `completed`

Full details in `docs/delivery_process.md`.

### Key Packages

| Directory | Purpose |
|---|---|
| `ordelo/agents/` | LangGraph agent definitions and runner |
| `ordelo/agent_app_handlers.py` | Glue between agent tools, WhatsApp, and DB/webhooks |
| `watomation/` | FastAPI app, routers, WhatsApp handlers |
| `ordelo_datamodels/` | Pydantic models and SQL schema definitions |
| `channels/telegram/` | Telegram bots (aiogram): registry, routers, DB wrappers over RPCs. See `docs/telegram-layer.md` |
| `utils_common/db_utils/` | Supabase REST + psycopg async pool operations |
| `utils_common/thread_management/` | LangGraph thread CRUD (ThreadHandler) |
| `utils_common/waba_utils/` | WhatsApp message senders |
| `utils_common/lg_utils.py` | LLM instance, prompt builders, agent factory |
| `config/` | Settings loaded from AWS Secrets Manager / env files |

### Database & Data Access

- **PostgreSQL via Supabase** — primary data store
- **Async pool**: `AsyncConnectionPool` (1–5 connections) via `pg_settings`
- **REST clients**: `client_ordelo` (Supabase REST, anon key) for CRUD operations; `client_ordelo_service` (service-role key, bypasses RLS) only for server-only objects such as the `t_invites` RPCs — **synchronous/blocking**; always wrap in `asyncio.to_thread()` when calling from an `async def`. The codebase has existing violations of this rule, but all new or changed code must follow it.
- **Pydantic models** in `ordelo_datamodels/` with class methods like `.from_rest_ref()`, `.from_customer_id()`
- **No full ORM** — mix of Pydantic + raw SQL + Supabase REST

### Database-backed logic: RPC pattern and cross-references (good practice)

When a feature needs rules or multi-step changes in the database, put that logic in a **Postgres function (RPC)** and keep the Python thin. Reference example: `channels/telegram/invites.py` wraps `t_invite_preview`, `t_claim_invite` and `t_linked_restaurants`, all defined in `ordelo_datamodels/telegram/create_t_invites.sql` (see [`docs/telegram-layer.md`](docs/telegram-layer.md)).

1. **RPC owns the logic.** Atomic, race-safe rules (claims, status changes, uniqueness) are one SQL function returning `jsonb` with a `result` string, not a read-modify-write sequence in Python.
2. **Define RPCs where the tables are defined.** The table(s), view(s), RPCs, grants and operator SQL live in the same SQL file, and that file lives in a **feature folder** of `ordelo_datamodels/` (`telegram/` for the `t_` layer, `restaurant_admin/` for the restaurant kitchen actions; add a folder for a new feature). It is the authoritative description of how the feature works in the database, so it is never filed under `migrations/`, which is only for one-off schema changes. Give the file a header: what it adds, how the pieces fit with other tables and services, lifecycle, security model, not-yet-done. Keep it idempotent.
3. **One Python wrapper module per domain.** A typed `async def` per RPC, `asyncio.to_thread` around the Supabase call, a small outcome dataclass. Handlers call the wrapper; they never query the table or repeat the rule.
4. **Cross-reference both ways, in the same change.**
   - The wrapper's **module docstring** names the SQL file that defines the RPCs and maps each Python function to the RPC it calls.
   - The SQL file's **header** names the Python module and functions that call each RPC.
   - The feature's doc (for Telegram: `docs/telegram-layer.md` section 6, and its HTML companion) has a row per database object with its defining file, Python caller and tests.
   - When you add, rename or change an RPC or table, update all of these together. Never leave a docstring pointing at an old name.
5. **Lock server-only objects.** Enable RLS on the table, `REVOKE ALL ... FROM PUBLIC, anon, authenticated` on its functions and views, and call them with `client_ordelo_service`. The anon `client_ordelo` is denied by design.
6. **Tests fake the RPC contract.** Mimic the RPC's return shapes in a fake (see `FakeInviteDb`), cover every `result` value, and change the fake whenever the RPC changes.
7. **Apply the migration before deploying** the code that calls it, and provide a drop/cleanup script when you rename database objects.

### Configuration

All secrets loaded via `config/aws_setting.py` from AWS Secrets Manager with fallback to local `.env_ordelo_agent`, `.env_ssm`, `env.json`. Key config modules:

- `config/pg_setting.py` — DB URI, Supabase client, async pool
- `config/waba_setting.py` — WhatsApp Business Account credentials
- `config/llm_setting.py` — ChatOpenAI instance
- `config/params.py` — Dynamic webhook URL building per restaurant
- `config/microservices_setting.py` — Payment/pricing/maps endpoints

Runtime configuration stored in `ordelo_config` DB table, keyed by restaurant (e.g., `{REST_REF}_DELIVERY_TIMEOUT_TIME`).

## Conventions

- **Python 3.13.11** required (`pyproject.toml`)
- **UV** for dependency management
- **Hatchling** build backend
- **Service naming**: `{Domain}Service` suffix, PascalCase (e.g., `DispatchService`)
- **Async-first**: handlers use `async/await` throughout
- **Linting**: Ruff with `F` rules only (`F704` ignored)
- **Testing**: pytest + pytest-asyncio, tests in `tests/`, mocks for external deps (psycopg, langgraph, pywa, config)
- **Live testing**: `ordelo_datamodels/misc_sql/test_restaurant_notices.sql` (fake `STRK-TEST-*` orders, stages 0-10) is the reusable harness for restaurant-admin flows on WhatsApp and Telegram; read `docs/live-order-test-harness.md` first and change the script and `tests/sql/test_restaurant_notices_script_sql.py` together
