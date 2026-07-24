# Ordelo Books — Business Plan & Product Spec (Round 3)

**The WhatsApp quarter-close agent for accountants. Clients keep their habits; practices keep their margin.**
Byteloop AI Ltd · v1 · 11 July 2026 · Constraints honoured: two people, start small, invent nothing.

Facts: [`evidence-log.md`](./evidence-log.md) (P/M/S/C/Dv refs). Decisions: [`decision-log.md`](./decision-log.md). Assumptions are marked **(assumption)**.

---

## 1. The problem

Since 6 April 2026, sole traders and landlords earning over £50,000 must keep **per-transaction digital records** (date, amount, category) and file **quarterly updates** with HMRC — ~780,000 people this year, ~970,000 more from April 2027, with the £20,000 tier announced for 2028 (M1, M2, M4). The first quarterly deadline in British history lands **7 August 2026** (M3).

The people doing the filing are accountants — agents file 59% of self assessment returns (M7). Their clients did not become digital because the law changed: 59% of accountants report at least half their income-tax clients still aren't using digital tools (M8). What clients actually do is what they've always done — **send a blurry photo of a petrol receipt on WhatsApp** and consider the job done. That exact sentence opens an industry article published yesterday (M9). Chasing the rest costs professionals up to 20 hours a month `[vendor-sourced]` (M10), and January's cleanup now happens **four times a year** on top of the unchanged SA season — the profession calls 2026-27 the "double workload" year (M9, M11).

The profession's published coping strategy is to **surcharge "WhatsApp-habit" clients** with premium fees and clean-up phases (M9). Nobody has removed the cost; they're just re-billing it.

## 2. The insight

The client's habit is not the problem — it's the interface. The industry built every piece around that habit except the piece that does the work:

- **Dext** built the *letterbox with OCR* — its WhatsApp channel receives receipts, but chases nothing and knows nothing about obligations (C1).
- **ClientWindow** built the *pipe* — WhatsApp routed into office inboxes, where humans still read every image (C5).
- **Snyp / Receiptor** built the *scanner*, sold to the sole trader, not the practice (C2, C3).
- **Practice management** built the *reminder email* — ~20% open rates, task-aware but not record-aware (C6).

Missing: the **clerk**. A stateful agent that holds each client's quarter — what's been captured, what's missing, what the practice's cut-off calendar says — lives in the client's existing WhatsApp thread, turns photos/PDFs/voice notes into compliant transaction records, chases *specifically the gaps*, escalates exceptions to humans, and hands the practice a review-ready cumulative update (M4, M5). Every competitor validates one face of this; none occupies the intersection (§4 of evidence log).

That intersection is Byteloop's production pattern already running in Ordelo: **dispatch → accept/verify → escalate → complete**, per-party threads, timers, audit trail — now with a receipt-shaped payload instead of a rider-shaped one.

## 3. The product — practice-scoped agent, four flows

**Capture flow (multimodal, per client thread).** Client sends what they already send: photo receipt (≤5MB), PDF bank statement or invoice (≤100MB), voice note "forty quid diesel this morning" (P1). The agent extracts date/amount/category per M4, echoes back a one-line confirmation in plain English ("Logged: £40.00, Motor expenses, 11 Jul — reply *fix* to change"), stores source media against the record for audit, and flags low-confidence extractions instead of guessing. Unreadable image → immediate "can you resend that one, closer up?" — at capture time, not at quarter end.

**Chase flow (the differentiator).** The agent knows each client's obligation calendar and the practice's internal cut-offs (the profession already sets these — e.g. records in by ~14 July for the 7 August deadline, M9). It chases in **escalating waves** against actual gaps, not generic reminders: "3 weeks of June statements missing"; "12 transactions need a category — 2-minute job, want to do it now?" Waves use approved template messages; replies open the service window (P4). Exactly the offer-wave/timer mechanics of the dispatch engine.

**Quarter-close flow (practice console).** A production board per deadline: every client as a card — record-quality score, gaps, unresolved queries, ready-to-review state. One-click export or API push of clean per-transaction records into the practice's HMRC-recognised software or bridging tool (C7); cumulative correction next quarter is handled by design, since updates restate year-to-date (M5). We are **not** the filing software at v1 (R3-D8).

**Escalation flow.** Non-responders, ambiguous judgment calls (mixed personal/business spend — the "senior time" sink in M9), and anything tax-adjacent goes to a human with context attached ("chased 3×, last seen Tuesday; these 4 transactions ambiguous"). The agent does logistics and data hygiene; **judgment stays with the accountant** — same principle as Cover's "agent assigns offers, coordinator retains override."

**What we deliberately don't do at v1:** no tax advice, no filing to HMRC ourselves, no bank feeds (statement PDFs first; feeds when a design partner demands), no consumer product.

## 4. Engineering map (reuse, honestly estimated)

Rider StateGraph → client-quarter StateGraph: dispatch offer = chase wave; accept/decline callbacks = confirm/fix; verification = record confirmation; thread-per-rider = thread-per-client; pg triggers/pg_cron = cut-off timers and wave scheduling; delivery audit trail = HMRC-grade capture audit. New build: multimodal extraction pipeline (vision + speech-to-text models on receipts/statements/voice), category taxonomy per HMRC's update categories, record store with source-media linkage, practice console, Xero/QuickBooks/FreeAgent push. **(Estimate: substantial reuse of the coordination layer; the extraction pipeline is genuinely new — internal estimate, not fact.)** Meta-policy exposure: none identified — bookkeeping collection is ordinary business messaging (P4), unlike round 1's pharmacy constraint.

## 5. Business model

- **Per-practice platform fee + per-active-client fee**: £99/month per practice + £4/active client/month **(assumption)** — anchored so a 50-client practice pays ~£3.6k/yr against ~£12k/yr of chase time at 20 hrs/month × £50/hr `[anchors: M10 vendor-sourced; Snyp's £19/mo/business consumer price point C2; the premium-fee framing in M9]`. Undercuts what surcharging recovers, so the practice can *keep* WhatsApp-habit clients profitably instead of shedding them. Sanity check from the state itself: HMRC prices the mandate's continuing cost at **~£110/yr per business** (M13) — £48/client/yr sits comfortably inside a cost the market has already been told to accept.
- Quarterly cadence = built-in retention: the product proves itself 4× a year on a dated deadline (M3).
- Expansion path: VAT-registered clients (same agent, existing MTD VAT), then the 2027 cohort lands +970k prospects on the same rails (M2).

## 6. GTM — smallest viable start

1. **Now → 7 Aug (first deadline):** watch, don't sell — collect the horror stories the first cycle generates in public forums; they're the sales deck for cycle 2.
2. **Aug–Sep 2026 — discovery, zero code:** 5–8 conversations with small practices in Bromley/SE London (same door-knocking muscle as rounds 1–2). Kill criterion below.
3. **Dogfood crossover:** Ordelo's existing restaurant partners are themselves sole traders in or near the mandate — a captive capture-flow test pool with a relationship already in place. **(Fit to be validated per-partner; income thresholds unknown.)**
4. **Oct–Nov 2026 — one design-partner practice, concierge quarter:** run their worst 10 "WhatsApp-habit" clients through the Q2 cycle (deadline 7 Nov 2026), hand-reviewing extractions behind the agent. Token pilot fee to test willingness to pay.
5. **Q3 cycle (7 Feb 2027) — productise for practices #2–#5.** January 2027's double workload (M11) is the sharpest sales moment of the year.

## 7. Competition & moat

Full map in evidence log §4. Threat ranking: (1) **Dext adds chasing** to its WhatsApp letterbox — most dangerous, watch quarterly; (2) **Xero's AI push** (M12) reaches practices through existing lock-in; (3) ClientWindow adds extraction. Moat honestly stated: none structural at day 1 — the defence is **speed through a live production cycle** (a working quarter-close is 4× harder to fake than a feature demo), practice-workflow depth incumbents treat as edge-case, and wedge-pricing under the surcharge norm. If Dext ships obligation-aware chasing before we have 5 practices, see kill criteria.

## 8. Kill risks

| # | Risk | Mitigation / kill criterion |
|---|---|---|
| B1 | Incumbent ships the clerk (Dext/Xero/ClientWindow) | Speed + depth; if shipped credibly before we sign practice #5, pivot to runner-up S5 or sell the extraction pipeline as their missing piece |
| B2 | Grace-year penalties (M6) make practices defer tooling to 2027 | Sell margin, not fear (M9/M10); if discovery says "we'll cope this year", target the Jan-2027 double-workload panic instead — calendar-shift, not kill |
| B3 | Practices shed WhatsApp-habit clients rather than tool up | Premium-fee norm (M9) says they'd rather monetise them; if discovery contradicts, the buyer becomes the shed clients' next (cheaper) practice — revisit model |
| B4 | Extraction accuracy on real-world blurry receipts below trust threshold | Human-in-loop concierge quarter first; confidence-flagging by design; kill if review overhead exceeds the chase time saved |
| B5 | GDPR/financial-data-over-WhatsApp objections | Processor terms, retention controls, UK hosting; ClientWindow's ISO27001 positioning (C5) proves the objection is answerable — budget for certification once revenue justifies |
| B6 | HMRC changes quarterly mechanics | Updates are cumulative and correctable (M5) — mechanics risk is low; monitor ICAEW/ATT guidance each cycle |

## 9. Sequenced runner-ups

1. **Trades voice-quote agent (S4)** — quantified pain, no clock; revisit if Books discovery fails.
2. **Staffing coordination + compliance docs (S5)** — best engine fit; fold into Ordelo Cover discovery (adjacent buyer).
3. **Property triage (S3)** — parked pending Awaab's-Law-to-PRS date.

## 10. Why this is the right third swing

Round 1 found a real problem blocked by Meta policy at the edge; round 2 found a real problem with no primary quote yet. Round 3 has what both lacked: a **statutory clock** (7 Aug 2026, then every quarter forever), a buyer whose own trade press published the exact complaint **yesterday** in the exact channel we serve, an incumbent map that validates every component while leaving the intersection empty, and a fourth-pillar fit where multimodality isn't a feature but the entire point — the product exists *because* the input is blurry photos, PDFs and voice notes. Ordelo moves food; Rx would move medicines; Cover moves carers; **Books moves the paperwork that all of them are drowning in.**
