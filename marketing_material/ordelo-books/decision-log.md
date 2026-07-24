# Decision Log — Autonomous Run, 11 July 2026 (Round 3)

Rule followed: act, write down why, keep moving. No mid-run questions asked; the one near-fork is documented at R3-D9. Evidence references are to `evidence-log.md` (P/M/S/C items).

---

**R3-D1 — Interpreted the brief as: pillars 1–3 + a fourth pillar (multimodal WhatsApp × GenAI), explicitly outside food/delivery.**
Founder-suggested candidate use cases (ID verification, translation, receipts, mortgage docs) were treated as hypotheses to test, not answers to confirm. Rounds 1–2 context (Ordelo Rx, Ordelo Cover) reread first so this round compounds: same brand system, same start-small constraint from round 2 (two people, no nationwide anything), same Bromley-first GTM muscle.

**R3-D2 — Selection criteria fixed before searching** (unchanged from round 1 D2, plus one): (1) pain severity & freshness, (2) WhatsApp-nativeness of users, (3) codebase reuse, (4) competitive whitespace, (5) regulatory feasibility for two people, (6) identifiable buyer with money and motive, **(7) multimodal essentiality — the play must *need* images/documents/voice, not merely tolerate them.**

**R3-D3 — Eight spaces scanned; three of the founder's four suggestions killed on evidence, one selected.**
Translation: Meta shipped it natively, free, on-device (P2) — no company there. Standalone ID verification: 34 DIATF-certified incumbents and a government register (S6) — it's a feature we integrate, not a business. Mortgage doc collection: Nivo has 100+ regulated institutions, free broker tier, and launched AI agents in April 2026 (S2) — validated and occupied. Receipts/records collection survived and sharpened into the MTD play (S8). This is the run working as intended: the brief said act as adversary; three suggestions died honestly.

**R3-D4 — Adversarial finding that reshaped the product: "WhatsApp receipt capture" is already a feature, not a company.**
Dext has a WhatsApp channel; Snyp, Receiptor AI and others sell WhatsApp capture from £19/mo (C1–C3). Consequence: the venture cannot be a scanner. The defensible unit is the **agentic production layer** — obligation-aware chasing, per-client quarter state, escalation, review-ready handoff — which no player in the map occupies (§4). The letterbox exists (ClientWindow), the scanner exists (Dext); the **clerk** doesn't.

**R3-D5 — Chose the accountancy practice as the buyer, not the sole trader.**
(a) Leverage: one practice sale = tens-to-hundreds of mandated clients; ~59% of SA returns are agent-filed (M7). (b) Money and motive: the profession's own press now advises surcharging "WhatsApp-habit" clients (M9) — the cost is recognised and priced, so software that collapses that cost has an obvious value anchor. (c) Two-person GTM: practices are reachable one at a time, starting locally, like round 2's agencies. Selling direct to sole traders = consumer churn economics against Snyp's £19/mo — rejected.

**R3-D6 — Timing call: this is the sharpest dated pain of the three rounds.**
Mandate live since 6 Apr 2026; **first-ever quarterly update due 7 Aug 2026 — 27 days out** (M3); 59% of accountants report half+ of clients still not digital (M8); the flagship complaint scenario was published *yesterday* (M9). Counter-fact logged rather than hidden: quarterly-update penalties are waived for 2026-27 (M6), so urgency rests on practice margin (M9, M10, M11), not client fines. I judged margin pain the stronger, more reliable driver — it recurs every quarter regardless of HMRC grace.

**R3-D7 — Runner-ups sequenced, not discarded.**
Trades voice-note→quote agent (S4): real, quantified pain (~8 hrs/wk, £17k–£25k/yr), genuine multimodal fit, but crowded job-app field, churn-prone one-person buyers, no forcing clock. Temp-staffing coordination/compliance (S5): best engine fit after Books, but multi-sided and dependent on certified-IDSP integration; adjacent to Ordelo Cover — fold into Cover discovery rather than a separate swing. Property triage (S3): thesis right, wedge taken (AskLettie/Fiixit); revisit only if Awaab's-Law-to-PRS extension gets a date.

**R3-D8 — Product boundary: we are not the filing software (v1).**
MTD submissions must flow through recognised software (C7). V1 pushes clean per-transaction records into the practice's existing stack (or bridging) instead of pursuing HMRC recognition ourselves — smaller regulatory surface, faster to revenue, consistent with "platform for the high street, not replacement of it." Becoming recognised software is a deliberate later step once volume justifies it.

**R3-D9 — The near-fork: double down on MTD-Books vs trades-quoting. Resolved without asking.**
Books won on 6 of 7 criteria (freshness, buyer, whitespace-at-the-intersection, reuse, regulatory conveyor of 780k→+970k→£20k tier, multimodal essentiality); trades won only on absence of incumbent-response risk. The brief said ask only at a real fork; a 6-to-1 scorecard isn't one. The risk that makes it feel fork-like — Dext/Xero shipping agentic chasing (M12, R1) — is a speed problem, not a selection problem, and speed is the one lever a two-person team actually holds.

**R3-D10 — Naming and packaging.**
**Ordelo Books** — continues the function-word family (Rx, Cover, Books); says ledgers without saying tax. Alternatives considered: Ordelo Quarters (too MTD-coupled — the same agent serves VAT/CT later), Ordelo Collect (sounds like debt). Deliverables follow the house pattern: README, evidence log, decision log, plan+spec, one-pager in the Ordelo design system, because this folder is marketing material first.

**R3-D11 — Facts vs assumptions discipline (carried from D9/R2).**
Everything sourced lives in `evidence-log.md`; vendor statistics are tagged and never load-bearing alone; pricing and adoption figures in the plan are labelled **(assumption)** with their grounded anchors named. Verification pass re-fetched the load-bearing primary sources before delivery (see D12).

**R3-D12 — Verification pass outcome (run end).**
Fetched the HMRC policy paper directly. **Confirmed verbatim:** 6 Apr 2026 / >£50k; Apr 2027 / >£30k; Apr 2028 / >£20k (announced Mar 2025); "around 780,000 … a further 970,000"; quarterly reports are "interim cumulative reports" on fixed dates. **Strengthened:** gained a state-published pricing anchor — HMRC's own estimate of ~£320 transitional + ~£110/yr continuing cost per mandated business, and HMRC's stated expectation that MTD benefits agents (new M13; added to the plan's pricing rationale). **Weakened / caveated:** the 2026-27 quarterly-penalty grace (M6) rests on two independent secondaries after the LITRG fetch failed — caveat added to the evidence log; it is an *anti*-urgency fact, so the honest direction of error favours us being too cautious, not too bullish. The 7 Aug 2026 first deadline (M3) is corroborated by three independent secondaries plus arithmetic from HMRC's own "7th of the month following quarter end" rule and yesterday's AccountingWEB reference to "the 7 August 2026 quarterly update deadline" — treated as verified.
