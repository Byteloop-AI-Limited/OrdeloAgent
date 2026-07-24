# Evidence Addendum — Round 2 (Home-Care Cover), 9 July 2026

Round-1 evidence is reused, not repeated: see [`../drug-commerce/evidence-log.md`](../drug-commerce/evidence-log.md) §2a for the home-care base facts (111,000 adult-social-care vacancies at ~7% in 2024/25; the Homecare Association's 10 Mar 2026 description of coordinators firefighting — "messages go out to staff groups… often the answer is predictable"; family-side chaos on the Dementia Support Forum; rota churn burning carers out). New facts gathered this round:

## Market size and shape
- CQC-registered domiciliary care services in England grew from **8,414 (2017) to 15,232 (2025) — +81%** — while residential establishments *shrank* 6.2%. A large, fragmented, still-growing buyer base of mostly small providers. — [PolicyBee domiciliary care statistics](https://www.policybee.co.uk/blog/domiciliary-care-statistics)
- CQC applies the same registration standard to a one-person startup as to a multi-branch provider — relevant to us only as confirmation that **a pure software coordination layer does not itself deliver regulated activity** (the agency remains the registered provider; we never employ or supply carers in this scoping). — [CQC](https://www.cqc.org.uk/guidance-regulation/providers/registration/personal-care-registration-homecare-agencies), [Nursebuddy guide](https://nursebuddy.co/blog/cqc-registration-homecare)

## Cost of the problem (willingness-to-pay anchors)
- A care manager spends **~5 hours/week sorting rotas and shift cover — 260 hours/year**. `[vendor-sourced]` — [JMS-One](https://jms-one.uk/blog/view/the-true-cost-of-poor-workforce-management-in-health-care)
- Agency cover rates: standard domiciliary ~£24–£35/hour charged, complex £28–£45/hour; last-minute/short-notice work commands premium rates (£16–£22+/hour pay). `[vendor-sourced ranges from recruitment firms]` — [Priority Recruitment](https://www.priorityrecruitment.co.uk/blog/uk-care-pay-agency-rates-guide), [Cucumber Recruitment](https://www.cucumber-recruitment.co.uk/resources/blog/the-real-cost-of-agency-staff-in-care-homes/)
- Implication (arithmetic, not a sourced fact): every uncovered visit an agency fills internally instead of via a staffing agency avoids a £24–£45/hour external charge; every hour shaved off coordinator rota-firefighting is an hour of management payroll recovered.

## Competitive gap check
- **Florence**: fills rota gaps by broadcasting first to the organisation's own bank, then to its **100,000+ vetted temp network**; positioned around care homes/organisations and block shifts; acceptance notifications via SMS. — [Florence](https://www.florence.co.uk/care-organisations/employee-scheduling/), [Florence temp staffing](https://florenceapp.com/en/care-organisations/temporary-staffing/)
- **Birdie / CarePlanner**: full rostering suites (300+ agencies run CarePlanner+Birdie together); responsive-rescheduling features exist inside their apps. — [Birdie rostering](https://www.birdie.care/products/rostering), [Birdie+CarePlanner](https://www.birdie.care/integrations/birdie-and-care-planner)
- **iStaffRota** and similar: carer-facing mobile apps for rota/clock-in/notes. — [iStaffRota](https://www.istaffrota.com/solutions/care-workers/)
- Gap confirmed as scoped: incumbents require carers to live inside *their* app, and none found operating WhatsApp-native visit-cover; Florence's temp marketplace suits block shifts, not scattered 30–60-minute domiciliary visit runs. The Homecare Association piece confirms what actually happens at 7am: **coordinators blast WhatsApp staff groups by hand.** Nobody has productised the thing they already do.

## Honest limits of this evidence
- No direct quote yet from a Bromley-area agency owner — first discovery calls must supply this before any build (kill criterion in the brief).
- The 5 hrs/week and rate figures come from vendors with an interest in the conclusion; treated as directional anchors only, never load-bearing in pricing.
