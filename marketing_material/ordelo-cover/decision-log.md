# Decision Log — Round 2, 9 July 2026

New constraint from the founder: **two-person team, no nationwide launch, must start small.** Drug-commerce (Ordelo Rx) is parked for consideration in its own folder, with a one-pharmacy entry plan added. This round restarts the original brief under the new constraint, reusing round-1 research.

**R2-D1 — Re-scored the contenders with "smallest viable start" as a first-class criterion.**
The question changed from "best business" to "best business two people can start with one local customer." Re-ranking of the round-1 field:

| Contender | Small-start fit | Asset reuse | White space | Verdict |
|---|---|---|---|---|
| Home-care visit cover | One agency, one borough, SaaS — no marketplace needed | Dispatch engine offer/accept/verify maps 1:1; WhatsApp-native workforce | No WhatsApp-native player found; incumbents force carers into their apps; Florence is care-home/block-shift shaped | **Winner** |
| Wholesale order-capture agent | Good (one wholesaler at a time, pure software) | Agent pillar only; no dispatch reuse | Crowded: Rekki, Orderlion, Choco, Fresho — funded incumbents | Runner-up |
| AI phone answering (restaurants) | Good | Agent pillar | Saturated, incl. UK-specific vendors | Rejected |
| Local-retail same-day delivery | Uses riders | Rail only | Differentiation vs Gophr/Stuart weak; thin margins | Rejected |
| Tiffin/home-kitchen ops | Good | Agent pillar | Niche too small in UK; India players exist | Rejected |

**R2-D2 — Critical re-scoping that changes the round-1 verdict on home care.**
Round 1 rejected home care because the *marketplace* version (mobilising vetted carers across agencies) makes compliance vetting — DBS, right-to-work, training sign-off — the bottleneck, which is a vetting business two people shouldn't start. Round 2 scopes it as a **single-agency coordination tool**: the agent only broadcasts to the agency's *own, already-vetted* staff. No employment, no supply, no CQC-registrable activity on our side — the agency remains the registered provider. The compliance bottleneck disappears at this scope. Cross-agency pooling stays on the roadmap as a later, deliberate step (it will meet the vetting problem again — see risk table for what it will require).

**R2-D3 — Why home care beat wholesale (the only serious rival at this scale).**
Three reasons. (1) Asset reuse: visit-cover is mechanically Ordelo's dispatch loop — offer, accept/decline, verify arrival, complete — where wholesale order-capture reuses only the chat layer. (2) Competition: wholesale has four funded incumbents doing exactly the WhatsApp-order thing; care cover has none found operating WhatsApp-native (evidence addendum). (3) The buyer is local and reachable the same way restaurants and councillors were: on foot, in Bromley — 15,232 registered services in England means every borough has dozens.

**R2-D4 — Tool-first, not marketplace-first, also fixes cold start.**
A single-agency tool has no two-sided cold-start problem: the carers arrive with the agency. Florence's 100k temp network is unassailable head-on but irrelevant at this entry point — we productise the WhatsApp group the coordinator already blasts, inside one agency at a time.

**R2-D5 — Pricing: flat per-agency SaaS, no per-shift take.**
Per-filled-shift fees make us look like a staffing agency (bad category, invites rate comparison and procurement friction) and create an incentive misread (we profit from their sickness). Flat monthly per branch keeps it a tool. Price point (£99–£149/mo) is an assumption anchored to coordinator time cost and agency-cover avoidance, both flagged in the brief.

**R2-D6 — No new deck-scale artifact; a one-pager instead.**
Round 2's theme is starting small; the deliverable set is scaled to match (brief + logs + one-page HTML in the house design system). The full-deck treatment can follow once discovery calls validate.

**R2-D7 — What would reverse this decision.**
If 5–8 discovery conversations with Bromley-area agency owners don't independently confirm (a) uncovered-visit firefighting as a top-3 weekly pain and (b) that carers resist employer apps but live on WhatsApp, the wedge dies and wholesale order-capture (R2-D3's runner-up) gets the same treatment. Evidence addendum flags the missing primary quote explicitly.
