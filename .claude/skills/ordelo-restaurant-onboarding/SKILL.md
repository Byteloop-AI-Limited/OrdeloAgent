---
name: ordelo-restaurant-onboarding
description: Prepare or carry out Ordelo restaurant onboarding with restaurant_master records, restaurant-specific ordelo_config, menu table and seed SQL, backend/frontend registration, and launch verification. Use when adding a new restaurant or preparing its onboarding plan and SQL bundle; supports web-only onboarding and identifies extra WhatsApp-agent setup when requested.
---

# Ordelo Restaurant Onboarding

Produce a restaurant-specific plan and reviewable SQL/code changes from the current
implementation. The CRMS example is a starting point, not a set of defaults for
every restaurant. Creating an onboarding skill or SQL bundle does not authorize
running that SQL, deploying services, changing Meta settings, or enabling checkout.
Respect any execution authorization already supplied by the user.

## Establish scope and facts

Read the repository's `agents.md`/`AGENTS.md` and inspect git status. Determine
whether the request is plan-only, implementation, or authorized execution, and
whether the restaurant is web-only or also needs a WhatsApp agent. Ask only for
missing consequential inputs; continue independent preparation while waiting.

Read [the onboarding procedure](references/onboarding.md) for required inputs,
SQL deliverables, menu creation, service dependencies, and launch checks. It maps
the CRMS source files and explicitly identifies their obsolete instructions.
Read the current consumers before copying configuration keys or changing routing.

For database reads/writes, use the sibling
[database-operations skill](../database-operations/SKILL.md). For actual order
testing, use [ordelo-local-automatic-orders](../ordelo-local-automatic-orders/SKILL.md)
and `docs/test-orders.md`. Do not rerun SQL the user has already executed unless
they request it; verify existing state instead.

## Prepare the onboarding bundle

Unless the user chooses other paths, write a new `plans/onboard-{slug}-plan.md`
and `notebooks/db_queries/restaurant_queries/onboarding_{slug}/`. Include read-only
preflight, `restaurant_master` insertion, per-restaurant configuration, **`core/menus.sql`
to create `public.{slug}_menu`**, supplied menu seed data, test-window/go-live SQL,
and scoped rollback. Keep the shared `ordelo_datamodels/core/menus.sql` as the schema
reference rather than replacing its CRMS table for a new restaurant.

Use standalone statements with `RETURNING` or verification `SELECT`s for manual
SQL. Do not copy the CRMS transaction wrappers or routine `DO` blocks. Clearly
label incomplete drafts; never execute unresolved values. Check whether existing
rows/table/data belong to this restaurant before proposing an upsert or import.

Implement backend/frontend registration only within the requested scope. Keep
new web ordering paused until menu, payment, fulfilment, and operational evidence
supports the requested launch. Web-only restaurants have no `{REF}_APP_URL` and
need no restaurant-agents app.

## Report the outcome

Link the plan, SQL bundle, and changed code. Distinguish generated from executed
SQL, local checks from deployed evidence, and paused setup from live onboarding.
Record missing inputs, external dependencies, and the next concrete launch gate.
Skill validation or passing frontend tests alone does not prove order/payment
readiness.
