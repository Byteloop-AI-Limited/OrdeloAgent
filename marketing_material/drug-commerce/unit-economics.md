# Ordelo Rx — Unit Economics (working note)

Added 9 Jul 2026 in answer to: *who pays, and where does profit come from?* Grounded facts cite [`evidence-log.md`](./evidence-log.md); everything else is a flagged **(assumption)**.

> **⚠ Superseded in part — see §"Corrected delivery economics" at the bottom.** The founder supplied real ops data (rider cost ≥ £5–6 per on-demand drop), which invalidates the £2.50–£3.00/drop assumption below. The correction changes the delivery product's shape, not the SaaS line.

## Who pays what, when

| Phase | Patient pays | Pharmacy pays | Byteloop earns |
|---|---|---|---|
| Pilot (weeks 1–6) | ~£3.50/delivery **(assumption)** | Nothing | Delivery margin only |
| Post-pilot | ~£3.50/delivery | £79/month SaaS **(assumption)** | SaaS + delivery margin |

Two revenue lines, deliberately split: the **patient** funds the physical drop (YouGov's 40%-want / 18%-get gap is the demand evidence); the **pharmacy** funds the software layer (agent + console + audit exports), because the software is what recovers NHS money for them. We rejected a third line — per-booking fees on Pharmacy First consultations — as bad optics/contract risk (decision D6); bookings are the ROI story that sells the subscription instead.

## Per-pharmacy monthly model

**Delivery line.** An average pharmacy dispenses ~7,000 items/month (fact, NHSBSA). Items ≠ drops: a basket bundles several items — at ~2–3 items/basket **(assumption; no grounded UK figure found)** that's roughly 2,300–3,500 baskets/month. If 3–6% of baskets convert to paid delivery **(assumption)**: **~85–200 drops/month**. Patient pays £3.50; rider cost per batched midday drop £2.50–£3.00 **(assumption — real figure comes from our own food ops data in week 1 of pilot)**; Byteloop margin **£0.50–£1.00/drop → £40–£200/month**. Thin by design: the delivery fee's job is adoption and rider-trough utilisation, not profit.

**SaaS line.** £79/month. Marginal costs are WhatsApp API conversation fees (utility messages are the cheap category), LLM inference, and hosting — low pounds per pharmacy per month, so gross margin is typical-SaaS high **(estimate)**. This line is where the profit lives.

**Total per pharmacy: ~£120–£280/month revenue, ~80%+ of the margin from software.**

## The pharmacy's side of the ledger (why £79 clears)

- One recovered £1,000 threshold month (62% of pharmacies missed it in May 2025 — fact) pays for **a year** of the subscription.
- Five extra formally-logged consultations/month at £17 (fact) alone beat £79 — against a backdrop of 2+ unfunded corridor-consultation hours/day (fact).
- Delivery costs them nothing (patient-paid), versus running their own van/driver — the Gophr case study cites ~£600k saved over two years by one chain outsourcing `[vendor-sourced]`.
- Every patient kept from Pharmacy2U/Phlo protects recurring dispensing volume — qualitative but existential for a 65%-loss-making sector.

## What this looks like at the scale we're allowed (two people, one borough)

25 Bromley pharmacies (Phase 1 target) × £120–£280/month ≈ **£36k–£84k ARR run-rate**, plus better £/hour for the existing rider pool at midday. Honest read: that is proof-of-rail money, not a company. The company appears when (a) the South East corridor multiplies the pharmacy count, and (b) the same riders and dispatch engine carry a second vertical (see `../ordelo-cover/`) — the rail's fixed costs amortise across everything it moves.

## Sensitivities that decide the model (pilot must measure)

1. **Drops per pharmacy** — if real uptake is <40/month, the delivery line is noise and pricing should fold delivery into a higher SaaS tier.
2. **Rider cost per drop** — batching density (drops per midday run) decides whether £3.50 holds or needs a £4.50 tier for distance.
3. **Bookings attributable to the agent** — if the agent can't demonstrably push a pharmacy over a threshold band within 90 days, R2 (broke buyers) bites and the SaaS price is wrong.

---

## Corrected delivery economics (founder input, 9 Jul 2026)

**Ground truth from live Ordelo food ops: a rider drop costs a minimum of £5–£6.** This is the most grounded number in this document — it outranks every delivery assumption above.

**Consequence 1 — on-demand pharmacy delivery is dead.** £3.50 patient fee − £5.50 rider cost = **−£2/drop**. Charging patients £6.50+ to cover it would crush uptake against a £9.90 prescription-charge anchor and Pharmacy2U's free mail delivery. Point-to-point, food-style dispatch does not transfer to this vertical. Full stop.

**Consequence 2 — the viable shape is the scheduled round.** £5–6 is the cost of *one job*: ride out, wait, deliver one bag, ride back (~25–30 min of rider time, implying an underlying rider cost of roughly £12–£15/hour **(inference from the founder's figure)**). A pharmacy round is one pickup, many drops, no hot-food clock. Per-drop cost then = rider £/hour ÷ drops per hour:

| Drops per rider-hour | Cost per drop | £3.50 patient fee | £4.50 fee |
|---|---|---|---|
| 2 | £6.00–£7.50 | −£2.50 to −£4.00 | −£1.50 to −£3.00 |
| 3 | £4.00–£5.00 | −£0.50 to −£1.50 | −£0.50 to +£0.50 |
| **4** | **£3.00–£3.75** | **≈ break-even** | +£0.75 to +£1.50 |
| 5 | £2.40–£3.00 | +£0.50 to +£1.10 | +£1.50 to +£2.10 |
| 6 | £2.00–£2.50 | +£1.00 to +£1.50 | +£2.00 to +£2.50 |

**Break-even at £3.50 is ~4 drops/hour; the business needs ≥5.** In a 2–3-mile urban zone that means drops every 10–12 minutes — demanding but not absurd for a planned route.

**Consequence 3 — pharmacy demand can be *shaped* in a way food never could.** Repeat prescriptions recur on a predictable ~28-day cycle (1.16bn items/year is overwhelmingly repeats — see evidence log). The agent doesn't just take delivery bookings; it **steers them into rounds**: "Your area's delivery round is Tuesday and Thursday 12–2pm — £3.50 on round days, £5.95 for a same-day solo run." Predictable demand + steerable timing = manufactured density. This is the single strongest argument that the delivery line survives contact with the real rider cost — and it's also why one pharmacy isn't enough: ~8 drops/day (two pharmacies at mid-range uptake) supports one viable daily round; one pharmacy alone sits in the 2–4 drops/hour dead zone unless its patients cluster tightly.

**Consequence 4 — the profit centre was never delivery, and that's now load-bearing.** The SaaS line (£79/mo, high margin) is untouched by this correction. Worst case — batching density never materialises — delivery becomes a cost-pass-through option (patient pays true cost, ~£5.95) or is dropped, and the business survives as the WhatsApp agent alone. Honest cost of that fallback: differentiation against app-based incumbents (Healthera, Charac) narrows to the channel itself, and the "anti-Phlo rail" story weakens. So the pilot's #1 measurement changes: **not** "will patients pay £3.50?" but **"can two pharmacies' steered repeat cycles sustain ≥5 drops/hour on two round days a week?"** If no after 8 weeks, keep the agent, kill the rail.

**Engineering note:** the current dispatch engine is single-job-shaped (one dispatch → one rider → one drop). Rounds need a multi-drop route mode — offer a *round* to one rider, sequence 6–12 verified handovers inside it. Real but modest delta; the verification/ePOD mechanics reuse unchanged.
