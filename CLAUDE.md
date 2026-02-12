# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OrdeloAgent is an AI-powered on-demand food delivery orchestration system. It uses WhatsApp Business API as the primary interface for riders, restaurants, and customers, with a FastAPI backend, LangGraph agents for stateful rider workflow management, and PostgreSQL (via Supabase) for persistence and business logic.

## Commands

```bash
# Dev server
uvicorn watomation.fapp_ordelo_agent:app --reload

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
- `watomation/routers/takeaway_hooks.py` — takeaway restaurant flow
- `watomation/routers/order_hooks.py` — order management
- `watomation/routers/payment_hooks.py` — payment integration
- `watomation/routers/thread_hooks.py` — thread lifecycle

### Event-Driven Flow

PostgreSQL triggers fire webhook calls to FastAPI endpoints. Example: a `delivery_dispatch` INSERT trigger calls `/delivery-hooks/delivery-dispatch`. Handlers respond immediately and perform async work via FastAPI `BackgroundTasks`. Scheduled jobs run via `pg_cron`.

### LangGraph Rider Agent

The core agent is in `ordelo/agents/rider_agent.py`. It manages the inflight delivery workflow using a `StateGraph` with:

- **State** (`AgentState`): messages, dispatch_id, rider_name, confirmation codes, cancel state
- **Tools**: `send_delivery_instructions`, `send_start_live_tracking_link`, `verify_restaurant_confirmation_code`, `verify_customer_confirmation_code`, `cancel_delivery_before_pickup`, `terminate_delivery_job`
- **Nodes**: `agent_node` → `ToolNode` → `respond_node`
- **Persistence**: `AsyncPostgresSaver` (PostgreSQL checkpointer), thread-per-rider mapping

`ordelo/agents/agent_runner.py` contains helpers to invoke the graph (`run_rider_graph`), initialize state for new deliveries (`init_ordelo_graph`), and debug state (`debug_state`).

### WhatsApp Message Flow

```
WhatsApp Message → on_message_wa_handler.process_wa_msg()
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
| `utils_common/db_utils/` | Supabase REST + psycopg async pool operations |
| `utils_common/thread_management/` | LangGraph thread CRUD (ThreadHandler) |
| `utils_common/waba_utils/` | WhatsApp message senders |
| `utils_common/lg_utils.py` | LLM instance, prompt builders, agent factory |
| `config/` | Settings loaded from AWS Secrets Manager / env files |

### Database & Data Access

- **PostgreSQL via Supabase** — primary data store
- **Async pool**: `AsyncConnectionPool` (1–5 connections) via `pg_settings`
- **REST client**: `client_ordelo` (Supabase REST) for CRUD operations
- **Pydantic models** in `ordelo_datamodels/` with class methods like `.from_rest_ref()`, `.from_customer_id()`
- **No full ORM** — mix of Pydantic + raw SQL + Supabase REST

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
