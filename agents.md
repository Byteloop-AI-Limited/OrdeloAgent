# OrdeloAgent — Agents, Modules, and How Things Fit Together

This document maps the codebase structure and explains how agents, webhooks, messaging, and data layers work together. Use it as your starting point and as a quick index for searching code.


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
  - Graph + Tools: `ordelo/agents/rider_agent.py` — defines tools (send instructions, start live tracking, verify codes, end delivery), agent nodes, and graph wiring.
    - Send instructions: `ordelo/agents/rider_agent.py:245` (`send_delivery_instructions`)
    - Start live tracking link: `ordelo/agents/rider_agent.py:277`
    - Verify restaurant CC: `ordelo/agents/rider_agent.py:322`
    - Verify customer CC: `ordelo/agents/rider_agent.py:419`
    - End delivery: `ordelo/agents/rider_agent.py:560`
    - Main node: `ordelo/agents/rider_agent.py:612` (`agent_node`)
    - Respond node: `ordelo/agents/rider_agent.py:640`
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
  - Delivery timed out notify: `delivery_timedout`
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
- Rider taps a button → WhatsApp Callback → `on_callback_wa_handler.dispatch_response`. This validates state, updates status promptly via `initial_handle_of_rider_response`, and exits early for stale/timed‑out jobs.

2) Becoming Inflight and Initializing the Agent
- When a rider is assigned (DB transitions to inflight), a DB trigger calls `POST /delivery-hooks/delivery-inflight-graph-init` with `delivery_detail`.
- The route schedules:
  - Restaurant notification webhook (`post_rider_event_inflight`).
  - LangGraph init (`init_ordelo_graph`) which:
    - Generates an OwnTracks start link (`create_start_job_config`) and stores it in graph state.
    - Seeds messages so the agent chooses tools appropriately (send instructions → live tracking link).

3) The Rider Agent Flow in Practice
- Tools available:
  - Send instructions (pickup/drop + meta), and offer “Pickup/Dropoff Location” buttons which round‑trip back to agent via callback.
  - Send “Start live tracking” link (OwnTracks config). Send “Stop live tracking” at the end.
  - Verify restaurant and customer confirmation codes; on success the customer/restaurant webhooks fire and DB status is updated (`dispatch_complete_func`).
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
- Supabase RPC/functions (key ones referenced):
  - `dispatch_accept_func`, `dispatch_complete_func`, `process_delivery` (scheduled), `clear_dispatch` (testing), `init_delivery` (testing).
- LangGraph state checkpointing:
  - Postgres checkpointer (configured per‑message): `AsyncPostgresSaver` compiled into the rider graph. Thread context is mapped via `ThreadHandler` using the rider’s WhatsApp number.


## Configuration and Secrets

- All secrets/envs are loaded via `aws_setting.py` → `ordelo_agent_env` (Secrets Manager). Local fallback files: `.env_ordelo_agent` as a source to generate JSON (`upload_secrets.sh`).
- Critical config modules:
  - `config/waba_setting.py` — WABA credentials, clients, catalog helpers.
  - `config/pg_setting.py` — `db_uri`, `rest_url`, `rest_key`, `service_key`, async pool.
  - `config/params.py` — `get_webhook_url(rest_ref, type)` maps to restaurant‑specific webhooks.
  - `config/llm_setting.py` — LLM model and OpenAI key.


## Running Locally

- Install deps: `pip install -r requirements.txt`
- Run the app: `uvicorn watomation.fapp_ordelo_agent:app --reload --port 3100`
- WhatsApp webhook endpoint is provided by pywa_async (configured with your Business token/phone); ensure Meta configuration points to your accessible URL.
- DB checkpointer tables: run once if needed via `utils_common/thread_management/initialize_db.py` (creates LangGraph checkpoints schema).


## Extending the System

- Add a new tool for the Rider Agent:
  1. Implement async function in `ordelo/agents/rider_agent.py` (use `RunnableConfig`, `InjectedState`, and return a `Command` with updates).
  2. Wrap in `@tool` and add to `_rider_agent_tools` list.
  3. If state keys are new, extend `AgentState` TypedDict accordingly.
  4. If it needs DB access, use `pg_settings.client` (Supabase) or `get_pool()` (psycopg_pool).

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
- Mark job complete and stop tracking: `ordelo/agents/rider_agent.py:560`
- Generate OwnTracks config link: `ordelo/agent_app_handlers.py:148`
- Live map URL (server URL to maps page): `watomation/routers/location_hooks.py:74`
- Rider zone event → restaurant webhook: `watomation/routers/location_hooks.py:229`
- Dispatch webhook entry: `watomation/routers/delivery_hooks.py` (see route definitions)
- WhatsApp message entrypoint: `watomation/on_message_wa_handler.py:40`
- Active thread lookup/creation: `utils_common/thread_management/thread_handler.py`
- Supabase REST call helpers: `utils_common/db_utils/sbase_rest_ops.py`


## Notable Details and Caveats

- State and threads: The system relies on a `thread` table keyed by WhatsApp number; always ensure a thread exists before invoking the rider graph.
- Tool responses: Tool functions generally both send WA messages and return `Command` state updates; the agent node decides whether to call tools or respond.
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

