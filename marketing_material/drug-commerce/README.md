# Ordelo Rx — Opportunity Package

Autonomous research-to-business run, 9 July 2026. Brief: start from the open internet, find a real, painful, underserved problem close to Byteloop's three pillars (WhatsApp restaurant agents · WhatsApp gig/logistics coordination · deep technical capability), and design a business around it. Invent nothing; document every call.

**The answer in one line:** arm England's 4,900 independent pharmacies — losing patients to PE-backed mail-order consolidators while 650+ close a year — with a WhatsApp patient front door and a same-day delivery rail built on the dispatch engine Ordelo already runs in Bromley.

## Files

| File | What it is |
|---|---|
| [`evidence-log.md`](./evidence-log.md) | Every sourced fact, with URLs; vendor-interested stats flagged. Includes the eight problem spaces scanned and why the losers lost. |
| [`decision-log.md`](./decision-log.md) | Every judgment call (D1–D9) with rationale, including the adversarial finding that reshaped the product (Meta's prescription-drug policy) and why no mid-run questions were needed. |
| [`business-plan-and-product-spec.md`](./business-plan-and-product-spec.md) | The business: problem, insight, three-module product spec, engineering reuse map, revenue model, GTM, kill-risk table, sequenced runner-ups. Facts vs assumptions strictly separated. |
| [`pitch-ordelo-rx-v1.html`](./pitch-ordelo-rx-v1.html) | 8-slide deck in the Ordelo design system (same DS as `../pitch-councillor-v1.html`). Print-ready A4 landscape; sources footnoted per slide; assumptions tagged on-slide. |

## The case in five sourced facts

1. 650+ pharmacy closures in England in 12 months — worst in 20 years; 65% of survivors loss-making.
2. The South East — Ordelo's operating region — is England's worst pharmacy desert: 6,138 people per pharmacy (Gophr research, published 30 June 2026).
3. 40% of Britons want prescription delivery; only 18% have ever had it (YouGov).
4. WhatsApp is the single highest-reach app among UK adults 55+ (63%) — the pharmacy demographic that won't download Healthera, Charac, or the NHS App.
5. Pharmacies have lost £71.7m in missed Pharmacy First threshold payments — 62% of England's pharmacies missed the £1,000 monthly payment in May 2025 — plus £115m/yr to unlogged referrals. Recoverable NHS money a booking agent can capture, which is what pays for the subscription.

## Top risk, stated plainly

Meta prohibits promoting or facilitating the exchange of prescription drugs on WhatsApp. The product is designed inside the allowed envelope (utility notifications, service bookings, delivery-logistics scheduling — "your prescription is ready" is Meta's own permitted example), but the delivery-booking step needs legal review with a healthcare-experienced BSP before build. Kill criterion and fallback are in the plan (risk R1).
