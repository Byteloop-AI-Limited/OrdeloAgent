# Ordelo Rx at Two-Person Scale — the Minimum Viable Entry

Answering: *"As a two-person startup, I cannot go nationwide. Can I start this smaller?"*
Yes — and smaller than the Phase 0 in the main plan. Nothing below requires new hiring, new capital, or a nationwide anything. Facts are sourced in [`evidence-log.md`](./evidence-log.md); the rest is explicitly operational design.

## The one-pharmacy wedge (weeks 1–4, ~zero new code)

Start with **one pharmacy** within the existing Bromley/Chelsfield rider zone — ideally one whose owner you can reach through the same high-street/councillor relationships the food business already uses.

- **Concierge MVP, manual first.** The pharmacy keeps a list of housebound/regular patients who currently phone in. When a basket is ready, the pharmacist sends one WhatsApp message to Ordelo's existing ops number; you dispatch it through the engine exactly like a food order (the pharmacy is, mechanically, a restaurant with one menu item: "delivery"). No patient-facing agent yet, so the Meta-policy question (risk R1) barely arises at this stage — it's the pharmacy's normal notification practice plus a courier.
- **Patient pays the delivery fee** (~£3–£3.50, assumption) via payment link or on the doorstep. The pharmacy pays nothing during pilot — removes R2 (broke buyers) entirely from the first conversation.
- **ePOD from day one**: the existing verification-code/photo handover, exported weekly as a one-page audit sheet for the pharmacist. This is the artifact that sells pharmacy #2 and #3 — GPhC inspectors cite exactly this as notable practice.
- **Deliveries ride the food trough** (10:00–16:00), so marginal rider cost is near zero and the trough-fill hypothesis gets tested with real data.

## What "success" means before writing serious code

Over 4–6 weeks with one pharmacy: ≥10 deliveries/week by week 4; ≥60% of offered patients opt in; zero failed-delivery incidents without a clean return-to-pharmacy record; the pharmacist agrees to a testimonial + intro to their LPC contacts. If those don't hold in the best-case borough with a hand-held pilot, the thesis dies cheaply — that's the point.

## Then, and only then, the software ladder

1. **Weeks 5–10 — pharmacy console on WhatsApp** (mark-ready → auto-dispatch), replacing the manual relay. Still no patient-facing agent.
2. **Months 3–5 — patient notifications via the API** ("ready for collection", delivery booking) for the pilot pharmacies only, *after* the BSP/legal check on Meta policy (R1). SMS fallback wired in.
3. **Months 5+ — Pharmacy First bookings**, the £17/consultation + £1,000-threshold recovery hook, once there are 3–5 pharmacies generating patient threads.

Two people can run steps 0–1 alongside the food business: one owns pharmacy relationships + ops, one owns the (thin) engineering delta. Nationwide never appears in this plan; Bromley → neighbouring SE-London boroughs is the entire first-year map, and the South East being England's worst pharmacy-desert region means the beachhead *is* the best market, not a compromise.
