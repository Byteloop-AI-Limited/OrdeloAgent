<!--
Sync Impact Report:
- Version: Initial → 1.0.0
- Modified principles: All (initial creation)
- Added sections: Core Principles (5), Module Architecture Map, Performance & UX Standards, Code Quality Standards, Governance
- Removed sections: None
- Templates requiring updates:
  ✅ .specify/templates/plan-template.md (to be verified)
  ✅ .specify/templates/spec-template.md (to be verified)
  ✅ .specify/templates/tasks-template.md (to be verified)
- Follow-up TODOs: None
-->

# OrdeloAgent Constitution

## Core Principles

### I. Test-First Development (NON-NEGOTIABLE)

**All code changes MUST follow Test-Driven Development:**
- Write tests BEFORE implementation
- Tests must fail initially (Red)
- Implement minimal code to pass tests (Green)
- Refactor while keeping tests green (Refactor)
- User approval required before implementation begins
- No code merges without corresponding test coverage

**Rationale:** TDD ensures code correctness, prevents regressions, and serves as living documentation. It forces clear requirements definition before coding begins.

### II. API-First Architecture with FastAPI

**All functionality MUST be exposed through well-defined FastAPI endpoints:**
- RESTful API design principles mandatory
- Pydantic models for request/response validation
- OpenAPI documentation auto-generated and maintained
- Webhook endpoints for database-triggered events
- Async/await patterns for I/O-bound operations
- Clear separation between API layer and business logic

**Rationale:** API-first design enables modularity, testability, and future integration with external systems. FastAPI provides type safety and automatic documentation.

### III. Database-Triggered Webhooks Pattern

**Database operations MUST trigger FastAPI webhooks for complex workflows:**
- PostgreSQL functions construct JSON payloads
- Functions make HTTP POST requests to FastAPI endpoints using `http_post()`
- Empty payloads are acceptable and handled gracefully
- Function chaining allowed for complex workflows (e.g., `delivery_inflight_whook()` → `notify_missed_dispatches_for_order()`)
- CTEs for conditional database operations
- Boolean return values indicate success/failure

**Examples:**
- `notify_missed_dispatches()` - Handles missed delivery dispatches
- `delivery_inflight_whook()` - Delivery inflight tracking
- `delivery_dispatch_whook()` - Delivery dispatch notifications

**Rationale:** This pattern decouples database logic from application logic while maintaining real-time responsiveness. It leverages PostgreSQL's reliability for event triggering.

### IV. Observability & Structured Logging

**All operations MUST be observable and traceable:**
- Loguru for structured logging throughout codebase
- Log levels: DEBUG for development, INFO for operations, ERROR for failures
- Context-rich log messages with relevant IDs (order_number, rider_id, thread_id)
- LangGraph state inspection endpoints for agent debugging
- Thread lifecycle tracking in PostgreSQL
- Performance metrics for critical paths (delivery assignment, location updates)

**Debug endpoints required:**
- `/debug/state/{recipient}` - Agent state inspection
- `/debug/state/thread/{thread_id}` - Thread-specific debugging
- `/threads/{recipient}` - List conversation threads

**Rationale:** Production debugging requires comprehensive observability. Structured logs enable automated analysis and alerting.

### V. Code Quality & Documentation Standards

**Every Python file MUST maintain high-quality module docstrings:**
- Module docstring BEFORE all imports
- First line: Concise summary of core purpose
- Following lines indented (2 spaces) for editor folding support
- Sections required:
  - Dependencies (based on imports)
  - Workflow steps (bullet points)
  - Functions/Classes (exact names for searchability)
  - Key Functions (with brief descriptions)
- Docstrings MUST be updated with every code change
- No commented-out code in production files
- Type hints mandatory for all function signatures
- Pydantic models for all data structures

**Example format:**
```python
"""
This line includes summary
  . The dependencies based on imports
  . First step
  . Second step
  Functions/Classes
  . function_name_1
  . ClassName
  Key Functions:
  . main_function - Brief description of purpose
"""
```

**Rationale:** Comprehensive docstrings enable AI agents and developers to quickly locate relevant code. Consistent format improves searchability and maintainability.

## Module Architecture Map

**This section provides a comprehensive map of the codebase to help agents locate and edit code effectively. Each module's purpose and key components are documented based on module docstrings.**

### Core Agent System (`ordelo/`)

#### `ordelo/agent_app_handlers.py`
**Purpose:** Agent app handlers for Ordelo delivery agent workflows and WhatsApp integration
- Manages rider dispatch responses and delivery state transitions via WhatsApp
- Generates agent configuration links and job control (start/stop) configs
- Provides live map location URLs and tracking enablement checks
- Posts webhook events for customer and restaurant confirmation codes
- Sends delivery instructions via WhatsApp with pickup/drop-off details

**Key Functions:**
- `process_dispatch_response_from_rider_sync` - Handle rider accept/decline responses
- `generate_config_href` - Create configuration URLs for agent setup
- `get_live_map_location_url` - Generate live tracking URLs for orders
- `enquire_shift_availability` - Send shift availability inquiry using WhatsApp templates
- `post_rider_event_customer_cc` - Post customer confirmation code events

#### `ordelo/agents/agent_runner.py`
**Purpose:** Core agent runner for Ordelo's delivery workflow system
- Initializes and runs LangGraph-based agent workflows
- Processes messages between rider agents and WhatsApp interface
- Manages delivery job state through PostgreSQL persistence
- Coordinates with rider_agent for workflow execution

**Key Functions:**
- `run_rider_graph` - Executes rider graph and returns AI response
- `init_ordelo_graph` - Initializes delivery workflow for given detail
- `run_byteloop_agent` - Runs the Byteloop concierge agent

#### `ordelo/agents/rider_agent.py`
**Purpose:** LangGraph agent implementation for rider delivery workflow
- Implements rider agent nodes and tools using LangGraph and LangChain
- Manages delivery workflow from instructions to completion
- Handles live tracking, confirmation codes, and delivery status
- Uses LangGraph for state management and LangChain for tool definitions

**Key Functions:**
- `notify_food_ready_for_pickup` - Notifies rider about food readiness
- `send_pickup_location` - Sends restaurant location to rider
- `send_dropoff_location` - Sends customer location to rider
- `verify_restaurant_confirmation_code` - Validates restaurant code
- `verify_customer_confirmation_code` - Validates customer code
- `end_delivery` - Terminates delivery and tracking

#### `ordelo/agents/byteloop_agent.py`
**Purpose:** LangGraph orchestration for Byteloop's WhatsApp concierge agent
- Configures the prompt, tools, and runtime context for ReAct-style agent
- Handles customer chat interactions
- Triggers WhatsApp notifications
- Accesses shared resources (async Postgres pool, thread handler)

### WhatsApp Automation (`watomation/`)

#### `watomation/fapp_ordelo_agent.py`
**Purpose:** FastAPI application for Ordelo WhatsApp automation service
- Configures FastAPI routers and WhatsApp handlers for agent workflows
- Manages PostgreSQL checkpoints and Supabase-backed thread access
- Exposes diagnostic endpoints for debugging agent state and flows
- Serves as entry point when running OrdeloAgent with WhatsApp integration

**Key Endpoints:**
- `/details` - Returns WhatsApp business profile and callback info
- `/threads/{recipient}` - Lists conversation threads for a recipient
- `/debug/state/{recipient}` - Gets LangGraph debug stack for a recipient

#### `watomation/on_message_wa_handler.py`
**Purpose:** WhatsApp message handler for Ordelo delivery system
- Processes incoming WhatsApp messages from riders and customers
- Handles command parsing and execution for delivery operations
- Manages live location sharing and tracking
- Provides delivery status updates and notifications

**Key Functions:**
- `process_wa_msg` - Main entry point for WhatsApp message processing
- `live_location` - Handles live location updates from riders
- `reset_thread` - Resets conversation thread state
- `test_delivery` - Creates test delivery for debugging

#### `watomation/routers/delivery_hooks.py`
**Purpose:** Delivery webhook handlers for Ordelo delivery system
- Processes delivery-related webhook events from database triggers
- Manages delivery dispatch assignments and inflight tracking
- Implements function chaining pattern for complex workflows
- Handles missed dispatch notifications and rider communications

**Key Endpoints:**
- `/delivery/dispatch` - Processes dispatch assignments
- `/delivery/inflight` - Initializes inflight tracking
- `/delivery/missed-dispatches` - Handles missed dispatch cases
- `/delivery/timeout` - Handles delivery timeout events

### Data Models (`ordelo_datamodels/`)

#### `ordelo_datamodels/delivery_pymodels.py`
**Purpose:** Pydantic models for delivery-related data structures
- `DeliveryDetail` - Complete delivery order information
- `DeliverySummary` - Summary view of delivery with confirmation codes
- Includes computed properties (e.g., `google_maps_url`)

#### `ordelo_datamodels/location_pymodels.py`
**Purpose:** Pydantic models for location and tracking data

#### `ordelo_datamodels/customer_master_pymodel.py`
**Purpose:** Pydantic models for customer data

#### `ordelo_datamodels/restaurant_master_pymodel.py`
**Purpose:** Pydantic models for restaurant data

### Utilities (`utils_common/`)

#### `utils_common/lg_utils.py`
**Purpose:** Utility helpers for agent creation, orchestration, and shared LLM resources
- Agent builders: `create_agent*`, `agent_node`
- Shared resources: `LLM_4o` (LLM instance), embedding helper
- Misc utilities: message shortening, state extraction, graph visualization

**Key Functions:**
- `create_agent` - Create an agent with system prompt and tools
- `create_agent_with_tools` - Create agent with tool binding
- `get_llm_4o` - Get shared LLM instance
- `display_graph` - Visualize LangGraph structure

#### `utils_common/thread_management/thread_handler.py`
**Purpose:** ThreadHandler for asynchronous thread operations in Postgres
- Delegates thread operations to PostgreSQL functions
- Manages conversation thread lifecycle

**Key Methods:**
- `create_thread` - Creates a new thread via PostgreSQL function
- `get_active_thread` - Gets active thread and updates last_access_dtts
- `make_threads_inactive` - Marks threads as inactive
- `get_or_create_thread` - Gets existing or creates new thread atomically

#### `utils_common/db_utils/sbase_rest_ops.py`
**Purpose:** Supabase REST API operations
- `sbase_call_function` - Call PostgreSQL functions via REST
- `sbase_get` - Query tables via REST API
- `sql_to_supabase_rest` - Convert SQL conditions to REST format

#### `utils_common/waba_es/api_funcs.py`
**Purpose:** Utilities for WhatsApp Business Account (WABA) Graph API interactions
- Fetches assigned WABAs for the configured business/tech provider
- Lists phone numbers for a given WABA

**Key Functions:**
- `get_assigned_wabas` - Returns the WABAs assigned to the configured business
- `list_phone_numbers_for_waba` - Lists phone numbers for a WABA id
- `get_wabas_with_phone_numbers` - Returns all assigned WABAs and their phone numbers

### Configuration (`config/`)

#### `config/pg_setting.py`
**Purpose:** Manages PostgreSQL and Supabase settings
- Defines `PgSetting` class using `pydantic_settings`
- Initializes Supabase Client and AsyncClient
- Manages `AsyncConnectionPool` for direct PostgreSQL connections
- Configures `PGVector` instance for vector similarity searches

#### `config/llm_setting.py`
**Purpose:** LLM settings and client configuration
- Defines `LLMSettings` for OpenAI API configuration
- Provides `llm_client` property for ChatOpenAI instance

#### `config/waba_setting.py`
**Purpose:** WhatsApp Business Account settings
- Manages WABA credentials and configuration
- Provides WhatsApp client instances

#### `config/logger_setting.py`
**Purpose:** Loguru logger configuration
- Centralized logging setup for the application

## Performance & User Experience Standards

### Performance Requirements

**Response Time Targets:**
- WhatsApp message processing: < 3 seconds
- Delivery dispatch assignment: < 5 seconds
- Live location updates: < 2 seconds
- Database webhook triggers: < 1 second
- Agent state retrieval: < 2 seconds

**Scalability:**
- Connection pooling mandatory for all database operations
- Async/await for all I/O-bound operations
- Background tasks for non-critical operations
- Rate limiting on external API calls (WhatsApp, Google Maps)

**Resource Management:**
- PostgreSQL connection pool: min_size=1, max_size=5
- Connection timeouts: 10 seconds
- TCP keepalives enabled (60s idle, 10s interval)
- Graceful degradation when external services unavailable

### User Experience Consistency

**WhatsApp Interaction Standards:**
- Maximum 2 sentences per response (avoid verbosity)
- Professional and courteous tone always
- Use user's name only in important messages (first hello, difficult situations)
- Clear call-to-action buttons for rider responses
- Proactive notifications for delivery status changes
- Live location sharing with visual map URLs

**Error Handling:**
- User-friendly error messages (no technical jargon)
- Graceful fallbacks when services unavailable
- Clear instructions for recovery actions
- Logging of all errors for debugging

**Accessibility:**
- Support for both template and non-template WhatsApp messages
- Clear visual hierarchy in messages
- Confirmation codes prominently displayed
- Location sharing with multiple format options

## Code Quality Standards

### Code Organization

**File Structure:**
- One primary class or function group per file
- Related utilities grouped in submodules
- Clear separation of concerns (API, business logic, data access)
- No circular dependencies

**Naming Conventions:**
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- Descriptive names (avoid abbreviations unless standard)

**Import Organization:**
- Standard library imports first
- Third-party imports second
- Local imports last
- Alphabetical within each group
- Absolute imports preferred over relative

### Testing Standards

**Test Coverage Requirements:**
- Minimum 80% code coverage for new code
- 100% coverage for critical paths (delivery assignment, payment, confirmation)
- Unit tests for all business logic
- Integration tests for API endpoints
- End-to-end tests for complete workflows

**Test Organization:**
- Mirror source code structure in `tests/` directory
- Use `pytest` framework
- Fixtures in `conftest.py`
- Mock external dependencies (WhatsApp, Supabase, OpenAI)
- Test data factories for complex models

**Test Naming:**
- `test_<function_name>_<scenario>_<expected_result>`
- Example: `test_process_dispatch_response_when_accepted_updates_database`

### Security Standards

**Secrets Management:**
- All secrets in environment variables (never hardcoded)
- Use AWS Secrets Manager or equivalent for production
- `.env` files in `.gitignore`
- Separate credentials for dev/staging/production

**API Security:**
- Verify tokens for all WhatsApp webhooks
- Rate limiting on public endpoints
- Input validation using Pydantic models
- SQL injection prevention (parameterized queries only)
- HTTPS required for all external communications

**Data Privacy:**
- PII (customer phone numbers, addresses) logged only when necessary
- Sanitize logs before external sharing
- GDPR compliance for data retention
- Secure deletion of inactive threads

### Version Control Standards

**Commit Messages:**
- Format: `<type>: <description>`
- Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
- Example: `feat: add live location tracking for deliveries`
- Reference issue numbers when applicable

**Branching Strategy:**
- `main` branch always deployable
- Feature branches: `feature/<description>`
- Bug fixes: `fix/<description>`
- Pull requests required for all merges
- Squash commits on merge

## Governance

**Constitutional Authority:**
- This constitution supersedes all other development practices
- All code changes MUST comply with these principles
- Exceptions require explicit documentation and approval

**Amendment Process:**
- Proposed changes documented in `.specify/memory/constitution.md`
- Version incremented according to semantic versioning:
  - MAJOR: Backward incompatible governance/principle removals or redefinitions
  - MINOR: New principle/section added or materially expanded guidance
  - PATCH: Clarifications, wording, typo fixes, non-semantic refinements
- Sync Impact Report required for all amendments
- Dependent templates updated before ratification

**Compliance Review:**
- All pull requests verified against constitution
- Automated checks for code quality standards (linting, type checking)
- Manual review for architectural compliance
- Test coverage gates enforced in CI/CD

**Complexity Justification:**
- Any deviation from simplicity principles requires written justification
- Performance optimizations documented with benchmarks
- Third-party dependencies evaluated for necessity and maintenance

**Runtime Development Guidance:**
- Refer to module docstrings for component-specific guidance
- Use debug endpoints for troubleshooting
- Follow established patterns (database webhooks, agent tools, etc.)
- Consult architecture map for code location

**Version**: 1.0.0 | **Ratified**: 2025-10-21 | **Last Amended**: 2025-10-21
