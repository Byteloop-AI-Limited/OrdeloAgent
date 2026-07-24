# Decision Log — Autonomous Run, July 9 2026

Rule followed: act, write down why, keep moving. No mid-run questions were asked; no genuine fork required one (rationale at D8).

---

**D1 — Interpreted the brief through the existing pitch deck.**
Read `pitch-councillor-v1.html`. Extracted: brand (Ordelo, by Byteloop AI), live proof (487 orders — 370 delivery, 117 takeaway), economics (15% commission vs aggregators' ~35%), geography (Chelsfield/Bromley), narrative ("keep money on the high street"), and the design system (`ordelo-ds.css`). Every downstream choice had to compound with these assets, not sit beside them.

**D2 — Defined selection criteria before searching, to stop myself rationalising a favourite.**
(1) Pain severity and freshness — people complaining *now*, not evergreen listicle pain. (2) WhatsApp-nativeness of the users. (3) Reuse of the existing dispatch/agent codebase. (4) Competitive white space. (5) Regulatory feasibility for a two-person technical team. (6) Identifiable buyer with money and motive. Scored qualitatively; documented in evidence log.

**D3 — Scanned eight spaces, shortlisted two, chose pharmacy logistics as flagship.**
Spaces scanned: home-care shift cover, temp-staffing coordination, wholesale order capture, tiffin/home kitchens, AI phone answering, pharmacy access/delivery, same-day courier gap, local-retail delivery. Pharmacy won on every criterion at once: the sharpest evidence is 9 days old (Gophr, 30 Jun 2026); the worst-hit region is the South East — where Ordelo already operates; the buyer (4,900+ small independents, >49% of the market) is losing patients to PE-backed consolidators exactly the way restaurants lose margin to aggregators — meaning Ordelo's existing anti-aggregator story, councillor relationships, and high-street distribution transfer verbatim; and the deliverable demographic (older, app-averse, WhatsApp-first) matches the channel. Home care had comparable pain but its bottleneck is compliance vetting, not coordination — wrong first wedge (full reasoning in evidence log §2a).

**D4 — Adversarial finding: WhatsApp bans prescription-drug commerce. Redesigned around it rather than ignoring or abandoning.**
Meta's policy prohibits promoting/facilitating exchange of prescription drugs, but explicitly allows pharmacies on the API for utility messaging ("your prescription is ready") and medical services (bookings, consultations). Consequence baked into the spec: the agent is a **logistics and services layer, never a medicines storefront** — no catalogue, no drug promotion, no in-chat payment for POMs; payment collected only for delivery fees and services, with dispensing decisions staying entirely with the pharmacist. Flagged as residual risk R1 requiring legal review with a Meta Business Solution Provider before build.

**D5 — Chose "arm the independents" over "become a digital pharmacy."**
Phlo/Pharmacy2U prove demand but require becoming a regulated pharmacy (capital-heavy, and it makes 4,900 independents your enemy). The infrastructure play sells to them instead — consistent with Ordelo's restaurant model: platform for the high street, not replacement of it.

**D6 — Patient-paid delivery, SaaS for the agent; no per-consultation referral fee.**
Delivery fees are patient-paid (YouGov demand data supports willingness; exact price is an assumption, flagged in the plan). The agent is a flat monthly subscription. I rejected charging pharmacies per Pharmacy First booking: skimming NHS service fees invites contractual/optics problems and complicates the pitch. Bookings are a retention feature that pays for the subscription instead.

**D7 — Deliverable format.**
Markdown business plan + product spec (substance, reviewable), plus a pitch deck in the existing Ordelo design system (usable marketing material — this is the marketing_material folder). Evidence and decisions in separate files so every claim can be audited against guardrail #1.

**D8 — Why no questions were asked.**
The one real fork was flagship choice (pharmacy vs home care). The evidence was not balanced — pharmacy dominated on 5 of 6 criteria — so per instructions I acted as my own adversary (D3, and "Kill risks" in the plan) and moved on. Runner-up is fully documented so the choice is reversible.

**D10 — Verification pass corrected two claims before delivery.**
Re-fetched the two most load-bearing primary sources. (1) Pharmacy First: the threshold payment is £1,000/month at 30 consultations (£500 is only the interim 20–29 band); total missed is £71.69m and 62% of England's pharmacies missed the payment in May 2025 — stronger than the initial search summary; all three deliverables corrected. (2) BSP pharmacy-onboarding guidance (tyntec, 2021) is narrower than 2026 policy summaries — medical services + opt-in transactional notifications only, retail customer-support excluded. The tension is now stated explicitly in the evidence log and folded into risk R1 rather than papered over.

**D9 — Facts vs assumptions discipline.**
Everything sourced lives in `evidence-log.md`. The plan's unit economics use clearly-labelled assumptions (delivery price point, adoption rates, delivery mix) because no grounded UK per-drop pharmacy pricing benchmark was found in-run; the £600k/2yr chain saving (Gophr) and Phlo's 4-hour windows are the closest grounded anchors. Vendor-interested statistics are tagged `[vendor-sourced]` and never load-bearing.
