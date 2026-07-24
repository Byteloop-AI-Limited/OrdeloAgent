# Ordelo Cover — Business Brief & Product Spec (Round 2)

**The WhatsApp visit-cover agent for homecare agencies. One agency at a time, starting in Bromley.**
Byteloop AI Ltd · v1 · 9 July 2026 · Constraint honoured throughout: two people, no nationwide anything.

Facts: [`evidence-addendum.md`](./evidence-addendum.md) + round-1 [`../drug-commerce/evidence-log.md`](../drug-commerce/evidence-log.md) §2a. Decisions: [`decision-log.md`](./decision-log.md). Assumptions are marked **(assumption)**.

---

## 1. The problem

Every morning in a homecare agency office: sickness calls land, rotas get reworked, and uncovered visits must be filled *now* — a missed visit means a vulnerable person without medication, food, or personal care. The sector runs at ~111,000 vacancies (7%); the Homecare Association's own description of the daily reality is coordinators blasting "messages out to staff groups" and phoning staffing agencies that usually have nobody. Families downstream get dinner visits at 3:30pm and bedtime visits at 10:20pm. The coordinator burns ~5 hours a week on this firefight `[vendor-sourced]`, and every externally-covered hour costs £24–£45 via staffing agencies `[vendor-sourced]`. England has 15,232 registered domiciliary services (+81% since 2017) — overwhelmingly small operators with exactly this morning.

## 2. The insight

The coordinator's emergency tool is *already WhatsApp* — an unstructured group blast, followed by phone-chasing, with no record of who saw what, no skills/geography matching, and no automatic rota update. Incumbent software (Birdie, CarePlanner, iStaffRota) solves rostering by making carers live in *their* apps; Florence solves block-shift gaps in care homes via a temp marketplace. Nobody has productised the WhatsApp blast itself — the one channel carers demonstrably already use. That is a dispatch problem, and Byteloop runs a production WhatsApp dispatch engine: offer → accept/decline → verify → complete. A care visit is a delivery with a person-shaped payload and stricter rules.

## 3. The product — single-agency scope (deliberately not a marketplace)

**Cover flow (the core).** Carer texts in sick → coordinator forwards, or marks visits uncovered → the agent works out which of the agency's *own* staff are eligible (skills flags, geography, hours caps — from the agency's data) → personalised WhatsApp offers go out in waves, not a scattergun blast → first eligible accept wins → everyone else auto-stood-down → rota record updated → optional "your carer today is Priya, arriving 12:30" message to the client's family. Full audit trail of who was offered what, when, and who accepted — evidence the agency can show CQC inspectors of a safe, managed response to disruption.

**Confirm flow.** Arrival/departure confirmation by the carer in the same thread (code or geo-stamped check-in — the existing verification mechanic), giving small agencies lightweight visit-assurance without forcing a new app on carers.

**Escalation flow.** Nobody accepts within the configured window → structured escalation to the coordinator with the ranked near-misses ("3 declined: distance; 2 no response") so the human phone-call minutes go only where they must.

**What we do not do at this scope:** no carer employment or supply, no cross-agency pool, no care planning/eCMAR, no payroll — we sit beside Birdie/CarePlanner (CSV/API import of rota + staff list), not against them, until an agency asks us to go deeper.

## 4. Engineering map

The rider agent's StateGraph is the cover agent: dispatch offer = visit offer; accept/decline callbacks unchanged; verification codes = arrival confirmation; thread-per-rider = thread-per-carer; pg triggers/pg_cron = offer waves and escalation timers. New build: eligibility/matching rules, rota import, audit export, family-notify templates. **(Estimate: majority reuse — same claim structure as round 1, same caveat: internal estimate, not fact.)** No Meta-policy exposure this time: workforce coordination is an unambiguous, permitted business-messaging use case — the round-1 R1 risk does not exist here.

## 5. Business model & the smallest viable start

- **£99–£149/month per agency branch, flat (assumption)** — anchored against ~5 coordinator-hours/week and one avoided agency-cover shift/month; no per-shift fees (decision R2-D5).
- **Week 1–3 — discovery, zero code:** 5–8 conversations with Bromley/SE-London agency owners (reachable through the same local network as the food business). Kill criterion: if uncovered-visit firefighting isn't independently named a top-3 pain, stop (R2-D7).
- **Week 3–8 — one design partner, concierge MVP:** run their real cover incidents through the existing engine with hand-configured matching; charge a token pilot fee to test willingness to pay.
- **Month 3–6 — productise for agencies #2–#5** in the borough. A borough with dozens of registered services supports the entire first year (15,232 in England ⇒ dozens per borough; exact Bromley count to be pulled from CQC's register during discovery).
- **Later, deliberately:** cross-agency mutual-cover pools (the Homecare Association piece explicitly imagines shared, verified capacity) — this re-introduces the vetting problem and only happens with a compliance partner, once ~10+ agencies trust the tool.

## 6. Kill risks

| # | Risk | Mitigation / kill criterion |
|---|---|---|
| C1 | Pain is real but budget isn't — small agencies won't pay for "a better WhatsApp blast" | Token-fee pilot from week 3; if a design partner won't pay ~£50/mo for a working concierge service, kill or reprice |
| C2 | Rota-data friction: agencies' rosters live in Birdie/CarePlanner and owners won't export | Start with CSV import + manual sync in pilot; only build integrations against demonstrated demand |
| C3 | Incumbents ship a WhatsApp channel | Their architecture (carers in their app) and ours (carers in WhatsApp) are opposite bets; speed + single-borough depth is the only defence — accept and move fast |
| C4 | WhatsApp group habits are "good enough" for a 5-carer micro-agency | Target the 15–60-carer mid-tier where blast chaos actually bites **(sizing hypothesis for discovery)** |
| C5 | Safeguarding optics: automation must never decide *care*, only *logistics* | Agent assigns offers; coordinator retains override; every escalation lands on a human — stated in product principles from day one |

## 7. Why this is the right second swing

Same three pillars, same engine, same borough, same door-knocking GTM — but a buyer whose emergency is *hourly* rather than seasonal, no Meta-policy cloud, no regulator between us and revenue at entry scope, and a wedge (one agency's own staff) that two people can serve end-to-end while the food business keeps running. Ordelo moves food; Ordelo Rx would move medicines; Ordelo Cover moves the people who hold the whole thing up.
