# Ordelo Rx — Business Plan & High-Level Product Spec

**The WhatsApp front door and same-day delivery rail for Britain's independent pharmacies.**
Byteloop AI Ltd · working draft v1 · 9 July 2026

Every factual claim here is sourced in [`evidence-log.md`](./evidence-log.md). Numbers that are design choices or estimates are explicitly marked **(assumption)**. Judgment calls are traced in [`decision-log.md`](./decision-log.md).

---

## 1. The problem, in one paragraph

England is losing pharmacies at the fastest rate in twenty years — 650+ closures in the last twelve months, 65% of the survivors trading at a loss — while the prescription load *grows* by 83.5m items a year. The South East, Ordelo's home region, is the worst-hit in the country: 6,138 people per pharmacy and rising. Patients feel it as queues and travel; 40% of Britons say they'd have prescriptions delivered if they could, yet only 18% ever have. Into that gap have moved PE-backed consolidators — Pharmacy2U (3.5m items/month, mail-order, 3–5 days) and Phlo (VC-funded same-day digital pharmacy) — which don't serve independent pharmacies; they *drain patients from them*. The 4,900 small independents who hold 49% of the market have no digital front door and no delivery rail of their own. It is the restaurant/aggregator story again, one high street over.

## 2. The insight

Three facts compose into the wedge:

1. **The heaviest prescription users are the least app-willing** — and pharmacy-app incumbents (Healthera, Charac, NHS App, Hey Pharmacist) all require a download and an account. Meanwhile WhatsApp is the *single highest-reach app among UK adults 55+* (63%), used by 92% of UK adult smartphone users. The channel the incumbents can't use is the one the patients already have open.
2. **Ordelo already built the hard part.** A live WhatsApp dispatch engine — job offer → accept/decline → live tracking → code-verified handover — running real deliveries in Bromley today. GPhC inspectors explicitly cite time-stamped electronic proof of delivery as notable practice for medicines delivery. Ordelo's verification-code handover *is* that audit trail, already in production.
3. **Pharmacies are leaving NHS money on the table that a booking agent can capture.** Missed Pharmacy First threshold payments total £71.69m — in May 2025, 62% of England's pharmacies missed the £1,000 monthly payment (30 consultations; interim £500 band at 20–29). Informal referrals cost pharmacies another £115m/year; the biggest barrier is patient awareness. A WhatsApp agent that converts "is my prescription ready?" conversations into *booked, formally-logged consultations* (£17 each, plus pushing the pharmacy over the £1,000 monthly threshold) pays for itself out of NHS money the pharmacy is currently losing — not out of new spend.

**Position: don't become a digital pharmacy. Arm the 4,900 independents against the ones that did.**

## 3. The product — three modules on one rail

### Module 1 · Patient front door (WhatsApp agent)
The pharmacy gets a WhatsApp number (or upgrades its existing one) run by an Ordelo agent. Compliance boundary — hard-coded, non-negotiable, per Meta policy: **the agent never promotes, sells, or catalogues medicines.** It does only what Meta explicitly permits for pharmacies:

- **Ready-for-collection notifications** ("Your prescription is ready" is Meta's own example of an allowed utility message), cutting counter queues and uncollected-item waste.
- **Delivery booking**: patient replies "deliver" → time window offered → patient-paid fee taken for the *delivery service* → job dispatched to Module 2. The pharmacist remains the sole decision-maker on what is dispensed.
- **Pharmacy First capture**: symptom mention ("can I ask about a UTI?") → agent signposts (never diagnoses) → books a formal consultation slot at the pharmacy → the visit is logged as a proper referral instead of an unfunded corridor chat.
- **Service bookings**: flu jabs, BP checks, NMS follow-ups — all "medical services," expressly allowed.
- **Repeat-cycle nudges**: "You ordered 28 days ago — reply YES and we'll ask your pharmacist to process your repeat." Request routing, not drug commerce.
- Escalation to a human (the pharmacy) on anything clinical, ambiguous, or upset.

### Module 2 · Delivery rail (the existing Ordelo dispatch engine, new cargo)
- Pharmacist marks a basket ready → dispatch offer goes to the shared local rider pool → accept/decline → pickup verification code at the counter → live-tracking link to the patient on WhatsApp → **delivery verification: code or photo ePOD, time/geo-stamped** — the GPhC-notable-practice audit trail, exportable per patient/per month for inspection.
- Exception handling designed for medicines, not meals: failed delivery → mandatory return-to-pharmacy protocol (never leave-on-doorstep); flagged lines (fridge items, controlled drugs) carry stricter handover rules — ID/signature capture where the pharmacist requires it; every leg logged against diversion-safeguard standards.
- The same riders who carry food at 12:00 and 19:00 carry prescriptions at 10:00–16:00. Pharmacy demand fills the food trough **(operating hypothesis to validate in pilot)** — better rider utilisation and earnings per hour without new supply acquisition.

### Module 3 · Pharmacy console
The pharmacist's side also runs on WhatsApp — mark-ready, view today's runs, trigger a notification — because a pharmacy that is 60%-likely to be short-staffed will not learn new software. A minimal web dashboard exists only for what chat is bad at: delivery audit exports, Pharmacy First booking logs, monthly reconciliation.

### What we deliberately do not build
No medicines catalogue or in-chat POM payment (Meta policy). No dispensing, no stockholding, no pharmacy licence (that's Phlo's capital sink, and it makes the buyer your competitor). No nationwide courier network on day one — density first, one postcode cluster at a time, the way the food side already works.

## 4. Engineering map (why this is weeks, not quarters)

| Ordelo (live today) | Ordelo Rx (delta) |
|---|---|
| LangGraph rider agent: dispatch → accept → verify codes → complete | Same graph; new cargo type, stricter exception states (return-to-pharmacy, ID handover) |
| Restaurant confirmation flows | Pharmacy mark-ready flow (simpler: no menu, no kitchen timing) |
| Customer WhatsApp ordering agent | Patient agent — *narrower* scope (notifications, bookings, delivery), plus a compliance guard layer |
| Live-location tracking links | Reused unchanged |
| PG triggers + pg_cron scheduled jobs | Repeat-cycle reminders, threshold-payment tracking |
| Thread-per-rider management | Thread-per-patient management, same infrastructure |

New build concentrates in: the compliance guard (intent classifier that hard-blocks medicine-commerce conversations), the audit-trail export, and flagged-cargo handover logic. **(Estimate, not fact: majority code reuse; the two-person team's own architecture supports it — see repo docs.)**

## 5. Business model

- **SaaS**: £79/month per pharmacy for the agent + console **(assumption; anchored loosely against what pharmacies already lose — 2hrs/day unfunded consultations and a £1,000/month threshold payment that 62% of pharmacies miss make the ROI story trivial to tell)**.
- **Delivery**: patient-paid per drop, ~£3.50 same-day within the local zone **(assumption; grounded only directionally — 40%-vs-18% unmet demand, Phlo normalising paid same-day windows)**. Rider paid from the fee; Ordelo margin per drop thin but positive; the strategic value is rider-pool utilisation across both verticals.
- **Explicitly rejected**: per-booking fees on Pharmacy First consultations (skimming NHS clinical fees is bad optics and worse contract exposure — decision D6). Bookings are the retention hook that justifies the SaaS line.

**Scale of the prize (sourced numbers, simple arithmetic):** 4,900 small-independent operators × £79/mo ≈ £4.6m ARR at full penetration of just the smallest ownership tier — before delivery margin, before medium groups (18% of market), before the runner-up verticals the same rail unlocks. The average pharmacy dispenses ~7,000 items/month; if even 3% of items convert to paid delivery **(assumption)**, that's ~210 drops/pharmacy/month — more weekday-daytime volume per pharmacy than a small restaurant produces in the food trough.

## 6. Go-to-market — the unfair part

Phase 0 (weeks 1–6): two pharmacies in the existing Bromley/Chelsfield operating zone, riders already on the road, councillor relationship already warm — the existing pitch deck's community framing ("keep the high street alive") applies to chemists even more sympathetically than to takeaways. Validate: delivery uptake %, food-trough fill, agent deflection of counter queries, one GPhC-inspection-ready audit export.
Phase 1 (months 2–6): 15–25 pharmacies across Bromley borough; recruit via the two pilot pharmacists' LPC (Local Pharmaceutical Committee) network. Begin measuring Pharmacy First booking lift against the £500 threshold.
Phase 2 (months 6–18): South East corridor — the worst pharmacy-desert region in England is Ordelo's back yard. Density before breadth; a new town only opens when a rider pool and 3+ pharmacies commit together.

## 7. Kill risks — the adversary's table

| # | Risk | Severity | Mitigation / kill criterion |
|---|---|---|---|
| R1 | **Meta policy interpretation.** Delivery-booking for an already-dispensed NHS prescription could be read by Meta as "facilitating exchange of prescription drugs." BSP onboarding guidance (2021, verified in-run) limits pharmacies to medical-service use cases + opt-in transactional notifications, excludes "retail customer support," and requires the WABA display name to reference the clinical service; 2026 policy summaries are more permissive ("prescription ready" utility messages allowed). The two sources are in tension. | Existential for Module 1 | Legal review + onboarding through an experienced healthcare BSP before build; structure the WABA around the pharmacy's clinical-services division per the onboarding guidelines; architecture keeps SMS/RCS fallback for the booking step. Kill Module 1 (not the company) if Meta refuses — the rail and console survive. |
| R2 | **Pharmacies are broke** (65% loss-making) — will they pay £79/mo? | High | Pitch is recovery of NHS money they already lose, not new spend. Pilot must show ≥1 monthly threshold payment (£500–£1,000) attributable to agent bookings within 90 days, or pricing model is wrong — renegotiate to success-share or kill SaaS line. |
| R3 | **Gophr moves up-stack** (they have the couriers *and* publish the desert research) or Healthera adds WhatsApp. | Medium | Speed + the piece neither has: a patient-facing agent (Gophr) / a rider network (Healthera). WhatsApp-native ops is Byteloop's whole stack, not a feature. |
| R4 | Controlled drugs / cold chain incident in delivery. | High reputational | Flagged-cargo protocol from day one; pharmacist decides per-item eligibility; insurance + SOPs reviewed against RPS safe-handling guidance before first POM drop. |
| R5 | Rider supply insufficient outside food peaks. | Medium | It's the *trough* being filled, not the peak (hypothesis) — pilot measures it; if wrong, restrict delivery windows to what supply supports. |
| R6 | NHS policy shift (e.g., national delivery funding) changes the game. | Low/slow | Would validate the category; Ordelo Rx becomes the delivery infrastructure commissioners buy. |

## 8. What "surprising" means here

The safe answer was another restaurant feature. The evidence pointed somewhere better: the same engine, the same riders, the same high-street politics — aimed at a market where the incumbent "aggregators" are PE-funds moving 3.5m items a month by second-class post, the customers are queueing pensioners, and the fix is a WhatsApp message their grandchildren already taught them to read. Ordelo for dinner; Ordelo Rx for everything the high street dispenses.

## 9. Runner-ups (kept warm, sequenced, not dropped)

1. **Ordelo Cover** — WhatsApp rapid shift-cover for home-care agencies (111k vacancies; coordinators already blasting "staff groups"). Enter after Rx proves the regulated-dispatch rail; the compliance-vetting bottleneck needs a partner, not a build. Evidence log §2a.
2. **Wholesale order-capture agent** — real 5–10% revenue bleed but a crowded vendor field (Rekki, Orderlion, Choco); only worth entering with a pricing weapon. Evidence log §2b.
3. AI phone answering and tiffin management — examined, rejected; saturated / too narrow. Evidence log §2c–d.
