# Ordelo Rx — Operations Spec: Rounds, Patients, and Proof of Delivery

v1 · 10 July 2026 · Companion to [`unit-economics.md`](./unit-economics.md) (corrected delivery economics) and [`business-plan-and-product-spec.md`](./business-plan-and-product-spec.md).
Grounded constraints are cited; everything else is operational design and marked as such where it matters.

## 0. Design principles (each one forced by a grounded fact)

1. **Rounds, not jobs** — rider cost ≥£5–6 per on-demand drop (founder ops data) means density is the whole economics. Everything below optimises drops-per-rider-hour.
2. **Not time-critical → scheduled labour.** Riders are booked for *round blocks* in advance at a block rate, not paid per-job gig premiums (founder's point — no hot-food clock means no urgency premium). The round is offered through the same dispatch offer→accept flow the food side uses.
3. **The agent never touches medicines commerce** — Meta policy (evidence log §1). It handles notifications with documented opt-in, delivery scheduling, and payment of the *delivery fee only*. Most patients pay nothing for the medicines themselves anyway: over 90% of items dispensed in England are exempt from the £9.90 charge ([NHS](https://www.nhs.uk/nhs-services/prescriptions/nhs-prescription-charges/), [CPE](https://cpe.org.uk/our-news/nhs-prescription-charges-to-remain-at-9-90/)) — so the £3.50 fee is typically the patient's only out-of-pocket cost.
4. **Byteloop never holds clinical data.** Basket contents stay opaque to us — "Package #4712, flags: FRIDGE" — with the pharmacy as data controller, Byteloop as processor. Health data is special-category under UK GDPR; the cleanest compliance posture is to never have it.
5. **Every handover produces evidence.** GPhC inspectors cite time-stamped ePOD/images as notable practice, no wet signature required (evidence log §1). The existing verification-code mechanic already exceeds this bar.

## 1. Patient onboarding

**At the counter (primary channel).** Pharmacist mentions the service at handout; patient scans a QR on the counter card → opens a pre-filled WhatsApp message ("START") → replies to confirm. That reply *is* the documented opt-in Meta requires for business-initiated notifications, logged with timestamp. The agent then collects, conversationally, the minimum set: delivery address, access notes ("ring twice, side gate"), preferred round day, and whether a proxy should be contacted instead.

**The existing delivery list (day-one volume).** Most pharmacies already keep an informal list of housebound/regular-delivery patients they phone by hand. During setup the pharmacist calls each one (they already do this monthly), gets verbal consent, and the agent sends a single opt-in confirmation template the patient answers YES to. No YES, no messages — they stay on the phone-call list as today.

**Proxy profiles (critical for this demographic).** The WhatsApp contact is often the adult child or carer, not the patient. A profile separates *recipient* (Mrs Hughes, 4 Elm Close) from *contact* (daughter, notifications + payment). One contact can manage several recipients; codes for handover go to whoever is registered as receiving the bag.

**What we never collect:** NHS number, medication names, conditions, exemption status. The pharmacy's PMR keeps all of that; our record is a person, an address, flags, and a message thread.

## 2. Batching: how rounds form

**Zones.** The pharmacy's delivery area is split into 2–4 zones (postcode sectors, ~1.5-mile radius each). Each zone gets fixed slots — e.g. Zone A Tue/Thu 12:00–14:00, Zone B Wed/Fri — published to patients as "your delivery day."

**Default-to-round pricing.** When the pharmacist marks a basket ready, the agent offers the patient's zone's next round at £3.50 as the default, same-day solo run at £5.95 as the premium exception, and free collection always listed. The price gap does the batching for us.

**Repeat-cycle pre-booking (the density flywheel).** Repeats recur ~every 28 days and 1.16bn items/year are dispensed mostly as repeats (evidence log §1). After delivery #1 the agent knows the cadence: "Your repeat's due around the 14th — shall I book you onto Thursday's round now?" Demand stops being random and starts arriving pre-batched. This is the structural advantage over food delivery, where demand can't be scheduled.

**Cutoff and manifest.** Round locks 90 minutes before departure (e.g. 10:30 for a 12:00 round). Pharmacist receives the manifest on WhatsApp — baskets, flags, sequence — bags and stages them. Late-ready baskets roll to the next round automatically, patient notified.

**Routing.** 6–12 stops sequenced by a simple travel-time optimiser; rider gets an ordered stop list with map links in the existing rider thread. No live re-optimisation needed — this is a milk round, not Uber.

**Thin-round rule.** If a round has <4 drops at cutoff (the break-even line from unit-economics): merge with the adjacent zone's round, or offer affected patients a free slide to tomorrow, in that order. During pilot, thin rounds still run — at a measured loss — because the data on *why* they're thin is what we're buying.

**Rider block booking.** Rounds are offered 24h ahead to the rider pool as fixed blocks ("Thu 12:00–14:00, ~10 drops, £X block rate" — rate to be set from food-ops data). Accept/decline via the existing dispatch flow. Regular riders get first refusal on their usual rounds — familiarity matters when the doorstep is an 84-year-old's.

## 3. Patient communication lifecycle (all WhatsApp, SMS mirror as fallback)

| # | Trigger | Message |
|---|---|---|
| 1 | Opt-in | Confirmation + what to expect (template, logged) |
| 2 | Basket ready | "Your prescription is ready" — Meta's own permitted example |
| 3 | Same message | Buttons: **Tue round £3.50** · Same-day £5.95 · I'll collect |
| 4 | Booking | Payment link for the delivery fee only; confirmation with date + 2-hr window |
| 5 | Round starts | "On today's round, arriving 12:00–14:00" + live-tracking link (existing capability) |
| 6 | 2 stops away | "About 15 minutes away" — the single biggest failed-delivery killer |
| 7 | At door | Handover per §4 |
| 8 | Done | "Delivered & verified 13:12" + reply-if-anything-wrong prompt |
| 9 | Day ~25 of cycle | Repeat nudge → routes the *request* to the pharmacist (never dispenses, never recommends) |

Anything clinical, ambiguous, or unhappy in any reply → thread handed to the pharmacy with full context. The agent's vocabulary is logistics.

## 4. Ensuring the medicine actually reaches the patient

Chain of custody, four links, each producing a record:

**Pickup.** Rider confirms basket IDs against the manifest at the counter; pharmacist releases with the existing pickup verification code. Custody transfer timestamped. Sealed opaque bags; flagged items visible to the rider only as handling codes (FRIDGE → insulated bag + max-out-time; CD/ID → see below).

**Transit.** Live location on (existing). No route deviations to new addresses — address changes only via the pharmacy, never negotiated at the kerb (diversion safeguard, per GPhC expectations on preventing diversion).

**Handover — tiered by risk:**
- *Standard:* 4-digit code sent to the registered contact's WhatsApp; patient or named proxy reads it to the rider; match = right package, right person, right address — timestamped. This is the food engine's existing mechanic doing exactly what GPhC's notable-practice guidance asks of ePOD.
- *No-code fallback* (no phone at the door — common with elderly recipients): geo/time-stamped doorstep photo + receiver name typed by rider. GPhC's cited practice explicitly accepts stamped images in place of signatures.
- *High-risk* (controlled drugs, pharmacist-flagged items): only carried if the pharmacist enables it per item; ID check + signature capture at the door; anything failing the check comes straight back.

**Hard rule: never leave on a doorstep.** No answer → rider re-attempts at end of round → still no answer → mandatory return to pharmacy, logged, patient auto-messaged with rebook options. At round close the manifest must reconcile: baskets out = verified deliveries + logged returns, pharmacist signs off. An unreconciled round blocks the rider's next block until resolved — that's the anti-diversion loop.

**Audit export.** Every delivery record (who booked, who received, verification type, stamps, photo reference) exportable per patient and per month — the inspection-ready artifact that sells pharmacy #2.

## 5. Pharmacy onboarding (half a day, no integrations)

Sign the data-processing agreement (pharmacy = controller, Byteloop = processor) → define zones and round slots → staff learn the two WhatsApp verbs they need (*mark ready*, *view manifest*) → counter QR cards out → call-down of the existing delivery list for consent. **No PMR integration at pilot** — basket ID + patient name is the entire interface; deeper integration only when an owner demands it. Riders serving pharmacy rounds carry enhanced vetting (DBS-checked) as a trust feature for pharmacists and families — positioned as standard for rounds serving vulnerable recipients **(design choice, not a legal requirement for couriers; verify insurer expectations before launch)**.

## 6. Open items to verify before launch

Meta/BSP confirmation of the notification + booking scope (risk R1, unchanged); insurer terms for medicines in transit including fridge/CD lines; the RPS safe-and-secure-handling checklist mapped onto the bag/seal/return SOP; and the block-rate that makes a 2-hour round attractive against food shifts — set from our own rider earnings data, not guessed.
