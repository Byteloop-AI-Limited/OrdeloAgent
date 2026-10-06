---
name: ordelo-local-automatic-orders
description: Run and document Ordelo local order tests using Chrome computer use, FastAPI Swagger, the restaurant frontend, database order tracking and Stripe test-mode verification. Use for local web or WhatsApp regression tests, R2 payment checks, and reversible test/production routing preparation.
---

# Ordelo Local Automatic Orders

Complete the requested test with current runtime evidence and a restoration record.
Choose the relevant path: fixture UI, real web-origin payment test, or WhatsApp
regression. A passing fixture checkout does not prove a real order or payment.

## Establish the current contract

1. Locate the checkout roots. On this machine they are
   `/Users/basavaraj/bloop/OrdeloAgent` and
   `/Users/basavaraj/bloop/restaurant-frontend`.
2. Read the applicable `AGENTS.md`/`agents.md`, `docs/local-testing-runbook.md`,
   and the release section of the user's plan (normally `plans/ordelo-agg-plan-cc.md`).
   Inspect git status to preserve unrelated work.
3. Inspect only the source needed to resolve the chosen test:
   - Backend entrypoint and routes: `watomation/fapp_ordelo_agent.py`,
     `watomation/routers/order_hooks.py`, `payment_hooks.py`, `delivery_hooks.py`.
   - Routing and payment mode: `config/params.py`, `config/feature_flags.py`,
     `utils_common/payment_ms/payment_mode.py`, `food_order_pymodel.py` under
     `utils_common/order_management/`.
   - Customer events: `utils_common/notify/customer_notifier.py` and its callers.
   - Frontend: `lib/web/mode.ts`, `lib/web/api.ts`, `config/restaurants.ts`,
     actual town/menu/order routes, checkout and configuration lookups.
4. Read the database-operations skill for database work. Read current scoped
   configuration; do not infer values from stale notes or `.env` variable names.
   Secrets come from the existing authorized configuration, not an `env.json` file.

## Select and run the test

- For service setup, logs, browser interaction, town-route 404s and the detailed
  Swagger/Stripe sequence, read [workflow.md](references/workflow.md).
- For configuration changes or restoration, read
  [configuration.md](references/configuration.md). It links the executable
  production-restore and test-enable SQL and explains the settings outside SQL.
- For runtime evidence use [inspect_order.py](scripts/inspect_order.py), a read-only
  database/optional Stripe-test inspector, and [inspect-order.sql](references/inspect-order.sql)
  for SQL-editor checks. These must run against the authorized project/database.

Before Python, activate the repo's `venv` or `.venv`, set `PYTHONPATH="$PWD"`,
then load `.env` with `envLoad`, following the runbook. Repeat in each shell.
Use current CUA documentation for computer use. Keep browser observation and
actions in CUA; query databases and provider APIs through their normal tools.

If configuration changes are part of the authorized test, record exact before
values and external webhook destinations before changing them. Shared
`ordelo_config` routing affects production consumers during this maintenance
window. Never turn a test request into permission for an unrelated deployment,
Meta change, live payment, or wider restaurant rollout.

For real web-origin tests, verify notifier coverage for that restaurant and
`payment_mode=test` before paying. Create a fresh W-id and WEB thread for each
order, reuse only an approved basket/address, and submit each create request once.
After an ambiguous response, look up the created order before any retry. Preserve
the whole returned Stripe URL, including its fragment. Follow current payment
handoff/approval requirements; a rejected final Pay click is not a payment.

For R2, prove authorization, payment-service persistence, Ordelo's single
initialization, exact-event replay, capture after rider acceptance, natural
no-rider cancellation on a separate order, and the actual browser redirect.
Do not force statuses or cancel in Stripe to make a natural-timeout check pass.
Use [workflow.md](references/workflow.md) for expectations and evidence limits.

## Finish with a reviewable record

Write `docs/releases/<test-scope>-<date>.md` with the environment, order/dispatch/
Stripe IDs, checks and observations, meaningful failures, logs inspected,
remaining gaps, temporary changes and verified restoration. Keep secrets,
payment credentials, and unnecessary personal data out of committed reports.
Use the client's timezone for human-readable times; label stored UTC timestamps.

Restore only recorded changes through the approved workflow. The production SQL
is a documented profile, not a substitute for a newer session's before snapshot.
Verify restored DB values and external destinations, account for caches, and
resolve remaining test jobs. Stop only processes started by this session, after
checking reload workers and listeners; preserve the user's servers and shared
tunnel. Report fixture, local real-order, external-provider and production
evidence separately. Do not call R3 verified when the test used Swagger.
