<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0
- Modified principles: placeholders → named principles
  - [PRINCIPLE_1_NAME] → I. API-First (FastAPI)
  - [PRINCIPLE_2_NAME] → II. Database-Triggered Webhooks to FastAPI
  - [PRINCIPLE_3_NAME] → III. Test-First (TDD)
  - [PRINCIPLE_4_NAME] → IV. Observability
  - [PRINCIPLE_5_NAME] → V. Simplicity, Security & Versioning
- Added sections: Architecture Constraints; Development Workflow & Quality Gates
- Removed sections: Placeholder example comments
- Templates requiring updates:
  - .specify/templates/plan-template.md — ✅ updated (footnote now references v1.1.0 and correct path)
  - .specify/templates/spec-template.md — ✅ verified (no changes required)
  - .specify/templates/tasks-template.md — ✅ verified (no changes required)
  - .specify/templates/agent-file-template.md — ✅ verified (no changes required)
  - .specify/templates/commands/* — ⚠ not present (no action)
- Follow-up TODOs:
  - Define concrete SLOs (p95 latency, error budgets)
  - Establish baseline metrics/traces and dashboards
-->

# OrdeloAgent Constitution

## Core Principles

### I. API-First (FastAPI)
- All external and internal interactions MUST be expressed as HTTP APIs implemented with FastAPI.
- OpenAPI schema is the source of truth. Any change to request/response MUST be versioned and reviewed.
- Endpoints MUST use consistent HTTP semantics (2xx success, 4xx client error, 5xx server error) and include validation with clear error messages.
- Public behaviors MUST be documented alongside example requests/responses.
Rationale: The project is a Python agent built on FastAPI; an API-first posture enables clear contracts and safe evolution.

### II. Database-Triggered Webhooks to FastAPI
- PostgreSQL functions MAY detect domain events and MUST call FastAPI webhooks via http_post() with JSON payloads.
- Payloads MUST be structured JSON; empty payloads are acceptable and MUST be handled as no-ops with 200 OK.
- Webhook endpoints MUST be idempotent or safe for retry; database-side functions SHOULD be retry-aware.
- Function chaining is allowed for composite workflows (e.g., a delivery inflight hook MAY call a follow-up notify function).
- Each webhook call MUST be logged with correlation IDs and execution outcome (success/failure, duration).
Rationale: Keeps DB logic close to data, while delegating orchestration to the app via well-defined webhooks.

### III. Test-First (TDD)
- Tests MUST be authored before implementation. Contract and integration tests define behavior; unit tests cover internals.
- Red → Green → Refactor cycle is enforced. Failing tests precede any code that makes them pass.
- Breaking changes MUST include updated tests and migration notes.
Rationale: Ensures behavior is specified, verifiable, and regression-resistant.

### IV. Observability
- All services MUST emit structured logs (JSON) with request IDs and principal identifiers where available.
- Key operations (API calls, DB-triggered webhooks, external I/O) MUST capture latency, status, and error metrics.
- Trace context SHOULD be propagated across API boundaries and webhook calls.
- Health, readiness, and liveness endpoints MUST be provided for runtime checks.
Rationale: Enables debugging, performance tuning, and reliability operations.

### V. Simplicity, Security & Versioning
- Simplicity: Prefer the minimal design that satisfies requirements. Avoid unnecessary abstractions and dependencies (YAGNI).
- Security: Secrets MUST NOT be committed; configuration comes from environment. Input validation is mandatory. Apply least privilege for DB and cloud roles. Logs MUST avoid sensitive data.
- Versioning: Use semantic versioning for the Constitution and APIs. Deprecations MUST include timelines and migration notes. DB functions and webhook endpoints SHOULD include versioned paths/names when behavior changes.
Rationale: Sustains maintainability and safe evolution.

## Architecture Constraints
- Language/Runtime: Python 3.11+.
- Frameworks: FastAPI for HTTP APIs; LangChain for agentic workflows as applicable.
- Data: PostgreSQL 14+ as primary store; PGMQ/message-queue patterns for async workflows when needed.
- Deployment: Containerized execution recommended; environment-parity across dev/stage/prod.
- Configuration: 12‑factor style via environment variables and secrets management.
- Performance: Establish and track p95 latency and error budgets for critical endpoints; webhook processing MUST be bounded and observable.

## Development Workflow & Quality Gates
- Branch naming: `[###-feature-name]` aligned with planning templates.
- Plans MUST include a "Constitution Check" and PASS before implementation.
- CI gates: lint, type check (if enabled), tests, and contract tests MUST pass before merge.
- PR reviews MUST verify adherence to the Core Principles and capture any required migration notes.
- Documentation: Public endpoints and webhook contracts MUST be documented and kept in sync with OpenAPI.

## Governance
- This Constitution supersedes other practices when in conflict.
- Amendments: Propose via PR updating `.specify/memory/constitution.md` with a Sync Impact Report. Include migration notes and template updates.
- Versioning policy: Semantic Versioning
  - MAJOR: Backward-incompatible changes to governance/principles
  - MINOR: New principles/sections or materially expanded guidance
  - PATCH: Clarifications and non-semantic edits
- Compliance: All PRs MUST demonstrate compliance. Plan/template footers MUST reference the current Constitution version and path.

**Version**: 1.1.0 | **Ratified**: 2025-10-04 | **Last Amended**: 2025-10-04