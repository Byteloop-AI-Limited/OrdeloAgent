# OrdeloAgent — Agents, Modules, and How Things Fit Together

> **Telegram layer:** [interactive guide](docs/telegram-layer.html) and [agent context](docs/telegram-layer.md) cover the restaurant-admin bot, the webhook route, the bot registry, the invite flow and the database-function (RPC) pattern with its cross-reference table. Add to the change log there whenever the Telegram layer changes.

> **Alerts and notifications:** [interactive guide](docs/alerts-and-notifications.html), [agent context](docs/alerts-and-notifications.md), and [canonical vocabulary](GLOSSARY.md) cover customer progress, restaurant-app callbacks, rider/admin alerts and overwatch. Existing transport statuses must not be described as confirmed message delivery.

> **Web ordering implementation:** see the [interactive playground](docs/web-ordering-playground.html) and [matching agent context](docs/web-ordering-playground.md) for checkout identity, tables, payment/fulfilment flows and differences from the separate proposal.

> **Payment services and testing:** [human guide](docs/test-orders.html) and [agent context](docs/test-orders.md) document the retained `payment` and `wrenPayment` endpoints. Only an exact `TEST3100` item selects test for a new order; test delivery offers go only to eligible overwatch riders. There is no retrospective order repair requirement.

This document maps the codebase structure and explains how agents, webhooks, messaging, and data layers work together. Use it as your starting point and as a quick index for searching code.

For local startup of OrdeloAgent and the sibling restaurant-frontend, Python shell preparation (`venv`, `PYTHONPATH`, `envLoad`), Cloudflare Tunnel routing, and maintenance-window test/production URL switches, follow the [local testing runbook](docs/local-testing-runbook.md).

## Project Skills

- **[telegram-api](.claude/skills/telegram-api/SKILL.md)** — Use for migrating this project's WhatsApp/PyWa messaging and handlers to Telegram with aiogram 3.31.0, or implementing Telegram interactions. Includes the Ordelo message inventory, official API documentation links, implementation examples, and source references for six FastAPI/aiogram repositories. Read the skill before Telegram migration work; preserve existing delivery/payment rules and LangGraph state.


## High‑Level Overview

- Domain: On‑demand delivery for restaurants with WhatsApp as the primary interface for riders/customers and a backend orchestrated via LangGraph + Postgres.
- Core runtime: FastAPI app integrates a WhatsApp client (pywa_async) and exposes webhook routes that are triggered by DB events (Supabase/Postgres) and third‑party services.
- Agents: LangGraph agents coordinate delivery workflows, persist state via a Postgres checkpointer, and interact via tools (send instructions, verify codes, live tracking links, etc.).
- Data: Supabase (Postgres) for delivery tables and functions; HTTP REST and direct pool (psycopg_pool) for reads/writes. Live location events captured from OwnTracks; location routing via webhooks.


## Key Components

1) FastAPI + WhatsApp Integration
- App entry: `watomation/fapp_ordelo_agent.py` — sets up FastAPI, configures WhatsApp client, registers message/callback/flow handlers, and includes routers:
  - Delivery webhooks: `watomation/routers/delivery_hooks.py`
  - Location hooks: `watomation/routers/location_hooks.py`
  - Twilio/web onboarding helpers: `watomation/routers/twilio_webhook.py`
- WhatsApp handlers:
  - Messages: `watomation/on_message_wa_handler.py:40` (`process_wa_msg`), plus utility commands (`/test`, `/reset`, `/live`, `/flow`).
  - Callback buttons: `watomation/on_callback_wa_handler.py:28` (`dispatch_response`) for Accept/Decline dispatch; `:85` (`rider_request_location`).
  - Flows (WA Flows): `watomation/on_flow_request_wa_handler.py` (Customer address capture) and `watomation/on_flow_request_postcode_search.py` (Postcode search).

2) Agents (LangGraph/LangChain)
- Rider Agent orchestration:
  - Graph + Tools: `ordelo/agents/rider_agent.py` — tools and graph for the inflight rider journey.
    - `send_delivery_instructions` — initial pickup/dropoff instructions.
    - `verify_restaurant_confirmation_code` — confirms pickup and marks `delivery_dispatch.status='pickedup'`.
    - `verify_customer_confirmation_code` — completes delivery and calls `dispatch_complete_func`.
    - `notify_pickup_time_adjusted` — notifies the inflight rider when the restaurant adjusts the pickup time (reads `pickup_time` from graph state, refreshed via `state_update_dict`).
    - `cancel_delivery_before_pickup` — rolls back an assigned dispatch pre‑pickup and reopens dispatching.
    - `terminate_delivery_job` — closes the delivery job/thread without a tracking link.
    - `request_rider_current_location` — sends the WhatsApp current-location prompt; only called when `wa_location_request_id` is set in graph state (see `ordelo/wa_location.py`'s `WaLocation._prompt_rider_via_agent`), so every location ask stays in the agent's thread history.
    - Graph control nodes: `agent_node`, `respond_node`, `ToolNode`.
  - Runner helpers: `ordelo/agents/agent_runner.py` —
    - Invoke graph per message: `:71` (`run_rider_graph`)
    - Initialize graph for accepted job: `:109` (`init_ordelo_graph`)
- General chat (Byteloop): `ordelo/agents/byteloop_agent.py` — minimal ReAct agent used for non‑delivery conversations.
- Shared LLM/utilities: `utils_common/lg_utils.py` — prompt builders, LLM instance, config/thread helpers, message/state utilities.

3) Application Handlers (Delivery Utilities)
- `ordelo/agent_app_handlers.py` — glue between graph tools, WhatsApp, and DB/Webhooks:
  - Generate OwnTracks start/stop config URLs: `:148` (`create_start_job_config`), `:204` (`create_stop_job_config`)
  - Delivery instructions: `:308` (`_send_delivery_instructions`)
  - Rider event webhooks: `:403` (`post_rider_event_customer_cc`), `:428` (`post_rider_event_restaurant_cc`)
  - Live map URL: `:258` (`get_live_map_location_url`)
  - Initial accept/decline handler: `:176` (`initial_handle_of_rider_response`)
  - Live location check: `:291` (`is_live_location_enabled`)

4) Webhooks and Routers
- Delivery hooks: `watomation/routers/delivery_hooks.py`
  - Dispatch to rider WA message: `wa_send_delivery_dispatch_request_to_rider`
  - Inflight init (DB trigger → init graph, rider notify): `delivery_inflight_graph_init_hook`
  - Missed dispatches notify + flag: `notify_missed_dispatches_hook`
  - Food ready notify via tool call: `notify_food_ready_for_pickup`
  - Pickup-time adjust (admin changes an already-set pickup time): `admin_order_reciept` sends +10/+20 buttons (`/AdminAdjustPickupTime{10,20}`) → `on_callback_wa_handler.admin_adjust_pickup_time` sets `delivery_summary.restaurant_confirmation_status='restaurant_pickuptime_adjusted'` → `trigger_restaurant_updates` → `restaurant_confirmation_flow` (`trigger_reason='restaurant_pickuptime_adjusted'`) → `_handle_restaurant_pickuptime_adjusted` resolves the inflight rider and runs `notify_pickup_time_adjusted`.
  - Delivery timed out notify: `delivery_timedout`
  - Availability enquiries (DB scheduled jobs → webhook → WA fan-out):
    - `shift_availability_enquiry_hook`
    - `admin_availability_enquiry_hook`
- Location hooks: `watomation/routers/location_hooks.py`
  - Live map redirect (Google Maps or map page): `live_location_map`
  - Rider zone events to restaurant webhooks: `notify_rider_location_event`
  - Prompt rider if tracking null/outdated: `notify_rider_null_or_outdated_location`
- Twilio/web onboarding: `watomation/routers/twilio_webhook.py` and `watomation/routers/twilio_webhook_utils.py`
  - WhatsApp Embedded Signup page + callback pipeline
  - Facebook Graph API integrations to onboard phone numbers and verify setup

5) Data, DB Helpers, and Models
- Supabase/Postgres settings and pool: `config/pg_setting.py`
  - Provides `pg_settings.client` (Supabase REST client) and `get_pool()` for async psycopg_pool.
  - Vector store integration (PGVector) configured but not central to rider flow.
- DB utilities (REST + pool): `utils_common/db_utils`
  - REST wrappers and SQL filters: `sbase_rest_ops.py` (call functions, select/insert/update/delete)
  - Async pool helpers: `sbase_pool_ops.py` (insert model, execute arbitrary SQL)
  - Realtime ref (example): `sbase_realtime_ref.py`
- Threading and LangGraph checkpointer
  - Threads table helpers: `utils_common/thread_management/thread_handler.py`
  - Checkpointer init script (one‑time): `utils_common/thread_management/initialize_db.py`
- Data models (Pydantic): `ordelo_datamodels`
  - Delivery and dispatch models: `delivery_pymodels.py`
  - Location model for OwnTracks payloads: `location_pymodels.py`
  - SQL: schema, functions, jobs in `ordelo_datamodels/*.sql`

6) Configuration and Settings
- Central import hub: `config/__init__.py`
- Project: `config/project_setting.py` (base URL, project root)
- WhatsApp Business: `config/waba_setting.py` (business account, provider, catalog helpers). Offers `_async_wa_client` and `_sync_wa_client`.
- Postgres/Supabase: `config/pg_setting.py` (URIs, REST URL/key, async pool)
- Webhook URL building: `config/params.py` (`get_webhook_url(rest_ref, type)`)
- LLM model/keys: `config/llm_setting.py`
- Logger wiring: `config/logger_setting.py`
- AWS Secrets loader: `aws_setting.py` (loads all env into `ordelo_agent_env`)

7) Edge Functions (Supabase Deno)
- App Runner manager: `utils_common/db_utils/edge_app_runner_manager.ts` — pause/resume AWS App Runner services via signed edge function.
- OwnTracks ingest: `utils_common/db_utils/edge_owntracks-webhook.ts` — push incoming OwnTracks JSON to `pgmq_public.send('owntracks')` queue.


## End‑to‑End: How the Pieces Work Together

1) Dispatch → Rider (Accept/Decline)
- DB trigger calls webhook: `POST /delivery-hooks/delivery-dispatch` with a list of dispatch payloads.
- `delivery_hooks.wa_send_delivery_dispatch_request_to_rider` builds “Accept/Decline” buttons with JSON callback payloads. Rider receives a WhatsApp message.
- Rider taps a button → WhatsApp Callback → `watomation/on_callback_wa_handler.dispatch_response`.
  - Validates the order still exists in `delivery_summary`.
  - If the order is already inflight:
    - Same rider + **Decline for the same `dispatch_id`** → treat as **pre‑pickup cancellation** and allow through.
    - All other taps are blocked with “already on job / taken by another rider”.
  - For non‑inflight orders, forwards to `ordelo/agent_app_handlers.initial_handle_of_rider_response`.

`initial_handle_of_rider_response` performs lightweight DB transitions:
  - Accept on `delivery_summary.status='unassigned'` → `delivery_dispatch.status='accepted'`.
  - Decline:
    - If the decline targets a dispatch already `status='assigned'`, the handler triggers the cancel path by running the rider graph with system message `call tool cancel_delivery_before_pickup`.
    - Otherwise it marks the dispatch `status='declined'`.

2) Becoming Inflight and Initializing the Agent
- When a rider is assigned (DB transitions to inflight), a DB trigger calls `POST /delivery-hooks/delivery-inflight-graph-init` with `delivery_detail`.
- The route schedules:
  - Restaurant notification webhook (`post_rider_event_inflight`).
  - LangGraph init (`init_ordelo_graph`) which:
    - Seeds messages so the agent sends delivery instructions; it does not create a tracking checkpoint.

3) The Rider Agent Flow in Practice
- Tools available:
  - Send instructions (pickup/drop + meta), and offer “Pickup/Dropoff Location” buttons which round‑trip back to agent via callback.
  - Native WhatsApp current-location responses are handled by `on_wa_location_handler` only when an authorised WaLocation request is pending.
  - Verify restaurant and customer confirmation codes; on success the customer/restaurant webhooks fire and DB status is updated (`dispatch_complete_func`).
  - Pre‑pickup cancellation:
    - `cancel_delivery_before_pickup` calls `dispatch_cancel_before_pickup`, reopens dispatching, and asks the rider for a reason.
    - `capture_reason_for_cancel_before_pickup` writes `reason_for_decline` and closes the rider job.
- On each incoming rider message, the WA handler `process_wa_msg` locates the active thread for that rider and runs `run_rider_graph(recipient, human_msg=...)`.
- The agent responds either directly (respond node → WhatsApp) or by executing tools (ToolNode), which themselves perform WhatsApp sends and DB operations.

4) Live Location
- The agent’s “Start live tracking” sends an OwnTracks configuration URL; the rider app begins publishing.
- OwnTracks webhook (either custom or Supabase edge) enqueues location; separate processes persist to `rider_location` and/or emit zone transitions into `rider_location_event`.
- Restaurant/customer webhooks for zone transitions are emitted from `location_hooks.notify_rider_location_event`.
- Live map URL can be requested: `/location-hooks/live-location-map/{order_number}` resolves current lat/lon and redirects to Google Maps.

5) Ending the Job
- After successful customer confirmation code verification, the agent calls DB function `dispatch_complete_func` and marks WA thread inactive. A “Stop live tracking” link is sent.
- `/reset` command exists to force thread reset; `/cleardis` calls a Supabase RPC to clear dispatch for testing.

6) Scheduled Availability Enquiries (DB → API → WhatsApp)
- Two non-critical “availability enquiry” flows are run via scheduled Postgres functions (typically via pg_cron) that call FastAPI endpoints.
- Shift enquiry (riders):
  - SQL function: `ordelo_datamodels/jobs_n_functions/enquire_shift_availability.sql` (`enquire_shift_availability()`)
  - Webhook endpoint: `POST /delivery-hooks/shift-availability-enquiry`
  - Handler: `watomation/routers/delivery_hooks.shift_availability_enquiry_hook`
  - Action: sends the `shift_availability` template with Yes/No quick replies.
- Admin enquiry (restaurant admins):
  - SQL function: `ordelo_datamodels/jobs_n_functions/enquire_admin_availability.sql` (`enquire_admin_availability(p_rest_ref_list VARCHAR[] DEFAULT NULL)`)
  - Webhook endpoint: `POST /delivery-hooks/admin-availability-enquiry`
  - Handler: `watomation/routers/delivery_hooks.admin_availability_enquiry_hook`
  - Action: sends the `alert_order_notification_resolve` template with a single quick reply.
- **Timeout behavior:** these endpoints respond success immediately and perform WhatsApp fan-out using FastAPI `BackgroundTasks` to avoid database-trigger HTTP timeouts.


## WhatsApp Handlers and Commands

- `process_wa_msg` — main message path for riders; runs the rider graph only if an active delivery/thread exists.
- Test commands (from `watomation/fapp_ordelo_agent.py` and `on_message_wa_handler.py`):
  - `/test` → `test_delivery`: seeds a test order and triggers DB functions to walk through the workflow.
  - `/reset` → `reset_thread`: closes inflight dispatch if any, marks threads inactive, and notifies.
  - `/live` → `send_live_map_location`: sends the live map URL if inflight exists and location is present.
  - `/flow` → `test_flow`: example WA Flow (UI screen) button to demonstrate flows.


## Data and Persistence

- Postgres/Supabase tables (most used):
  - `delivery_detail` (per‑order detail), `delivery_summary` (joined status view), `delivery_dispatch` (rider offers), `delivery_inflight` (active jobs), `rider_location`, `rider_location_event`, `thread` (agent chat context).
- Supabase RPC/functions follow one pattern: the logic lives in the database function, defined next to its table in `ordelo_datamodels/migrations/`, wrapped by one Python module, and both sides name each other (see "Add database-backed logic" under Extending the System). Telegram example: `t_invites` and `t_claim_invite` in `create_t_invites.sql`, called from `channels/telegram/invites.py`.
- Supabase RPC/functions (key ones referenced):
  - `dispatch_accept_func`, `dispatch_complete_func`, `dispatch_cancel_before_pickup` (pre‑pickup rollback), `process_delivery` (scheduled), `clear_dispatch` (testing), `init_delivery` (testing).
- Dispatch lifecycle data is stored per rider offer in `delivery_dispatch`:
  - Status progression includes `assigned` → `pickedup` → `completed`.
  - `reason_for_decline` (nullable) records explicit decline/cancel reasons per `dispatch_id`.
- LangGraph state checkpointing:
  - Postgres checkpointer (configured per‑message): `AsyncPostgresSaver` compiled into the rider graph. Thread context is mapped via `ThreadHandler` using the rider's WhatsApp number.

> **📖 For detailed delivery workflow documentation including all triggers, webhooks, and status transitions, see [`docs/delivery_process.md`](docs/delivery_process.md)**


## Configuration and Secrets

- All secrets/envs are loaded via `aws_setting.py` → `ordelo_agent_env` (Secrets Manager). Local fallback files: `.env_ordelo_agent` as a source to generate JSON (`upload_secrets.sh`).
- Critical config modules:
  - `config/waba_setting.py` — WABA credentials, clients, catalog helpers.
  - `config/pg_setting.py` — `db_uri`, `rest_url`, `rest_key`, `service_key`, async pool.
  - `config/params.py` — `get_webhook_url(rest_ref, type)` maps to restaurant‑specific webhooks.
  - `config/llm_setting.py` — LLM model and OpenAI key.


## Environment Setup

### Quick Setup (Recommended)

Use the automated setup script to create and configure the Python virtual environment:

```bash
source run_setup.sh
```

**What it does:**
1. Verifies `uv` is installed (modern package manager, 10-100x faster than pip)
2. Creates `.venv` using `uv venv`
3. Activates the virtual environment
4. Installs all dependencies from `requirements.txt` using `uv pip`
5. Sets `PYTHONPATH` to the project root
6. Verifies AWS environment variables are configured

### Manual Setup

```bash
# Create virtual environment with uv
uv venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt

# Set PYTHONPATH
export PYTHONPATH="$(pwd)"
```

**Note:** If `uv` is not installed, install it with:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Environment Requirements

**AWS Secrets (required):**
- `AWS_SETTINGS_KEY_ID`
- `AWS_SETTINGS_ACCESS_KEY`
- `AWS_SETTINGS_REGION`
- `AWS_SETTINGS_SECRET_NAME`

These are used by `aws_setting.py` to fetch secrets from AWS Systems Manager (SSM). They should be available in cloud sessions by default.

**Optional development dependencies:**
```bash
INSTALL_DEV=1 source run_setup.sh
```

### Cloud Session Notes

- This project uses **`uv`** for package management (faster, better dependency resolution than pip)
- Virtual environment activation doesn't persist across tool invocations in Claude Code
- The `run_setup.sh` script is idempotent and safe to run multiple times
- Prefers `.venv` over `venv` directory naming

> **📖 For detailed cloud session setup instructions, see [`.claude/CLOUD_SESSION_SETUP.md`](.claude/CLOUD_SESSION_SETUP.md)**

## Running Locally

- Prepare the Python shell before any Python command: activate `venv` (or `.venv`), set `PYTHONPATH="$PWD"`, and load `.env` with `envLoad`, as shown in the [local testing runbook](docs/local-testing-runbook.md).
- Run the app: `uv run watomation/fapp_ordelo_agent.py` (port 3100; add `--active` when using `venv`).
- WhatsApp webhook endpoint is provided by pywa_async (configured with your Business token/phone); ensure Meta configuration points to your accessible URL.
- DB checkpointer tables: run once if needed via `utils_common/thread_management/initialize_db.py` (creates LangGraph checkpoints schema).


## Extending the System

- Add database-backed logic (RPC pattern; reference: `channels/telegram/invites.py` + `ordelo_datamodels/migrations/create_t_invites.sql`):
  1. Put the rule in a Postgres function that returns `jsonb` with a `result` string (atomic, race-safe). Define it **in the same migration file as the table(s) it works on**, with the grants (`REVOKE ... FROM PUBLIC, anon, authenticated`, RLS on) and a header explaining what the file adds, how it interacts with other tables and services, its lifecycle and security model.
  2. Add one thin typed `async def` per RPC in a single Python module for that domain (`asyncio.to_thread`, `client_ordelo_service` for service-only objects, a small outcome dataclass). Handlers call the wrapper, never the table.
  3. **Cross-reference both ways in the same change:** the Python module docstring names the SQL file and maps each function to its RPC; the SQL header names the Python callers; the feature doc has a database-object ↔ code ↔ tests row.
  4. Mimic the RPC contract in the test fake and cover every `result` value. Apply the migration before deploying the code that calls it.

- Add a new tool for the Rider Agent:
  1. Implement async function in `ordelo/agents/rider_agent.py` (use `RunnableConfig`, `InjectedState`, and return a `Command` with updates).
  2. Wrap in `@tool` and add to `_rider_agent_tools` list.
  3. If state keys are new, extend `AgentState` TypedDict accordingly.
  4. If it needs DB access, use `pg_settings.client` (Supabase) or `get_pool()` (psycopg_pool).

  **Tool Authoring Checklist**
  - If the tool sends any WhatsApp message itself, return `ToolMessage(...)` then `AIMessage("/dontRespond: ...")` to suppress `respond_node`.
  - Add the tool to `_rider_agent_tools` and document it in `ordelo/agents/rider_agent_prompt.md`.
  - Use/extend `AgentState` for any new state fields.
  - Keep DB writes idempotent where possible (dispatch/inflight webhooks may re‑fire).
  - Update the module docstring in the file you edit.

- Add a new webhook:
  - Create a route in `watomation/routers/...` and include router in `fapp_ordelo_agent.py`.
  - If it’s DB‑triggered, have the DB function call your FastAPI endpoint with the necessary payload.

- New WA Flow (UI):
  - Register a `FlowRequestHandler` with endpoint and add DATA_EXCHANGE handlers as shown in `on_flow_request_postcode_search.py`.


## Quick Search Map (Common Tasks)

- Initialize graph after rider accepts: `ordelo/agents/agent_runner.py:109`
- Send delivery instructions: `ordelo/agents/rider_agent.py:245`
- Send start live tracking link: `ordelo/agents/rider_agent.py:277`
- Verify restaurant/customer confirmation codes: `ordelo/agents/rider_agent.py:322`, `:419`
- Pre‑pickup cancel + reason capture: `ordelo/agents/rider_agent.py` tools `cancel_delivery_before_pickup` and `capture_reason_for_cancel_before_pickup`
- Mark job complete and stop tracking: `ordelo/agents/rider_agent.py:560`
- Rider location prompt (agent tool): `ordelo/agents/rider_agent.py` tool `request_rider_current_location`, invoked from `ordelo/wa_location.py`'s `WaLocation._prompt_rider_via_agent`
- Generate OwnTracks config link: `ordelo/agent_app_handlers.py:148`
- Live map URL (server URL to maps page): `watomation/routers/location_hooks.py:74`
- Rider zone event → restaurant webhook: `watomation/routers/location_hooks.py:229`
- Dispatch webhook entry: `watomation/routers/delivery_hooks.py` (see route definitions)
- WhatsApp message entrypoint: `watomation/on_message_wa_handler.py:40`
- Active thread lookup/creation: `utils_common/thread_management/thread_handler.py`
- Supabase REST call helpers: `utils_common/db_utils/sbase_rest_ops.py`

## Pyrun Notes

Use pyrun for ad-hoc Python snippets. The skill assumes the environment is already set up.
If your pyrun attempt fails with an import error or missing module, run the setup script
and try again:

```bash
source run_setup.sh
```

Example (WABA webhook configuration via `config/waba_setting.py`):

```bash
python - <<'PY'
from config import waba_setting

business_phone_number = waba_setting._sync_wa_client.get_business_phone_number()
print(business_phone_number.webhook_configuration)
PY
```

Note: Ensure AWS secrets are loaded so `ordelo_agent_env` can populate settings.


## Notable Details and Caveats

- **SQL execution preference (2026-10-02):** Write SQL intended for manual execution as standalone statements without explicit `BEGIN`, `END`, or `COMMIT` transaction wrappers. Avoid `DO ... BEGIN ... END` blocks for routine configuration switches; prefer ordinary SQL statements. The user reported that the R3 configuration update persisted in the Supabase web SQL editor but did not persist when run as a transaction block in the VS Code PostgreSQL extension. This is an observed workflow issue, not a confirmed PostgreSQL defect. Include `RETURNING` or a separate verification `SELECT` for changes. This does not require removing procedural syntax needed inside existing function definitions or changing application transaction handling.
- State and threads: The system relies on a `thread` table keyed by WhatsApp number; always ensure a thread exists before invoking the rider graph.
- Tool responses: Tool functions generally both send WA messages and return `Command` state updates; the agent node decides whether to call tools or respond.
- **/dontRespond convention:** If a tool already sends a WhatsApp message (via `wa_client.send_message` / `send_location` / templates), the tool’s returned `Command` must include a `ToolMessage(...)` followed by an `AIMessage("/dontRespond: ...")`. This suppresses `respond_node` from echoing a second, near‑duplicate text to the rider.
- Edge side effects: Some helper modules in `utils_common/waba_es` run example calls on import; avoid importing them in production flows unless needed.
- README mismatch: The top‑level `README.md` describes a generic main/services layout that doesn’t reflect this repo’s structure. Prefer this `agents.md` for accurate navigation.


## File Index (Selected)

- App and routers
  - `watomation/fapp_ordelo_agent.py` — App + WA client + handler wiring
  - `watomation/routers/delivery_hooks.py` — delivery webhooks
  - `watomation/routers/location_hooks.py` — location webhooks and live map
  - `watomation/routers/twilio_webhook.py` — onboarding/testing helpers
  - `watomation/on_message_wa_handler.py` — WA message handlers and test commands
  - `watomation/on_callback_wa_handler.py` — WA button callbacks (Accept/Decline, etc.)

- Agents
  - `ordelo/agents/rider_agent.py` — tools, nodes, graph
  - `ordelo/agents/agent_runner.py` — invoke/init
  - `ordelo/agents/byteloop_agent.py` — simple chat agent
  - `ordelo/agents/rider_agent_prompt.md` — system prompt

- Config
  - `config/waba_setting.py` — WA clients (sync/async), catalog helpers
  - `config/pg_setting.py` — Supabase + psycopg_pool settings
  - `config/params.py` — webhook URL mapping per restaurant
  - `aws_setting.py` — secret loading to `ordelo_agent_env`

- DB and models
  - `utils_common/db_utils/sbase_rest_ops.py` — REST helpers
  - `utils_common/db_utils/sbase_pool_ops.py` — pool helpers
  - `utils_common/thread_management/thread_handler.py` — thread helpers
  - `ordelo_datamodels/delivery_pymodels.py`, `location_pymodels.py`

- Edge functions
  - `utils_common/db_utils/edge_app_runner_manager.ts` — AWS App Runner control
  - `utils_common/db_utils/edge_owntracks-webhook.ts` — OwnTracks → pgmq queue


---
If you want, I can add sequence diagrams (Mermaid) or short runnable examples per endpoint/tool to further accelerate onboarding.
