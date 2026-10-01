# ordelo-agg plan: decision log

- **Companion to:** `plans/ordelo-agg-plan-cc.md` (OrdeloAgent, branch `release/ordelo-agg`)
- **Session date:** 2026-09-29 (entries 23–26 on 2026-09-30, 27–33 on 2026-10-01)
- **Format:** Each entry records the question as it was put, the options offered (the recommended option is marked ★), the owner's answer **verbatim**, and how the plan applied it. `D#` refers to the decision table in §0 of the plan.
- **Interpretation notes:** where an answer needed interpretation, a note says so. Answers that departed from the recommendation are flagged **Override**.

---

## Summary

| # | Topic | Owner's answer (short) | Recommendation followed? | Plan ref |
|---|---|---|---|---|
| 1 | Plan location | OrdeloAgent/plans/ | Yes | D1 |
| 2 | Payment service ownership | We own it | Yes | D2 |
| 3 | WhatsApp number for web customers | New Ordelo customer number | Yes | D3 |
| 4 | Home of ordelo-agg-agent | New app in restaurant-agents | Yes | D4 |
| 5 | Phone verification | No OTP; Stripe checkout only | Partly (free-text) | D5 |
| 6 | Guest order access | Secret link + lookup fallback | Yes | D6 |
| 7 | When to choose delivery/collection and postcode | Postcode gate on landing | **Override** | D7 |
| 8 | Price authority | `_menu` prices are authoritative, no reprice | Free-text; superseded by #9 | D8 |
| 9 | Discounts, thresholds, vouchers (and prices) | Keep everything as today; move later | **Override** | D8 |
| 10 | Web thread_id | Real thread; later bring the customer into WhatsApp | **Override** (free-text) | D9 |
| 11 | Re-key vs link the web thread on WhatsApp opt-in | Link, don't re-key | Yes | D9 |
| 12 | Where web addresses live | Upsert customer_master (as today) | **Override** | D10 |
| 13 | Web collection pickup time | Same confirmation flow as WhatsApp; order page shows the time | **Override** (free-text) | D13 |
| 14 | Customer self-cancel | No self-cancel; call restaurant | Yes | D14 |
| 15 | Town membership and slugs | Frontend config for now | Yes | D18 |
| 16 | WhatsApp sender ≠ checkout phone | Allow, status only (with clarification) | Yes + clarification | D16 |
| 17 | Where the web customer enters a phone | Remove the phone dependency; random when absent | **Override** (free-text) | D12 |
| 18 | Web customer key | Synthetic W-id + Stripe-collected phone | Yes | D10, D11 |
| 19 | Channel schema | origin_channel + subscriptions + customer events | Yes | D15 |
| 20 | Pay-at-restaurant on web | Online payment only | Yes | D17 |
| 21 | Release order | R0–R5 as proposed | Yes | D19 |
| 22 | Shared-understanding check | Yes, write the plan | — | — |
| 23 | Do R0/R1 affect existing services? (Q&A, 2026-09-30) | Clarification only | — | R0/R1 guardrails |
| 24 | Same page for WhatsApp and web? (Q&A, 2026-09-30) | Asked for pros/cons | — | §8.1 |
| 25 | Ordelo storefront: web + ordelo-agg-agent share one page, same elements and offers | Stated by owner | — | D20 |
| 26 | Restaurant-specific UI: undecided; defer and note in plan | Stated by owner; recommendation agreed | Yes | D21, Q12 |
| 27 | Relax "web orders never reach restaurant apps"? (2026-10-01) | Keep the rule | Yes | D27, ADR-0003 |
| 28 | Payment-service changes for web (2026-10-01) | Keep its contract; change only Ordelo's payment-complete | **Override** | D22, ADR-0004 |
| 29 | Webhook signing (2026-10-01) | No signing secret exists; keep today's behaviour | **Override** | D23, ADR-0004 |
| 30 | Name and phone on web orders (2026-10-01) | Never collect | **Override** | D24, ADR-0005, Q14–Q16 |
| 31 | When web payments are captured (2026-10-01) | Manual capture; delivery captured when a rider accepts | Stated by owner | D25 |
| 32 | Post-payment redirect gap (2026-10-01) | Defer; document in the plan | Stated by owner | D26, §13.1 |
| 33 | Glossary and ADRs (2026-10-01) | Update CONTEXT.md and ADRs from the plan | Stated by owner | CONTEXT.md, ADR-0003–0005 |
| 34 | R1 readiness fixes (2026-10-01) | Storefront now; R2 creates a web-style order; Q17 out of R1 | Yes | D28, D29, D30 |
| 35 | Split R1; migrations as one SQL file run manually; implement Ordelo changes after the plan (2026-10-01) | Stated by owner | — | D30, D31 |
| 36 | Test payments from the restaurant UI via `isTest3100` (2026-10-01) | Overwatch for WhatsApp; test restaurants for web; both pages | Yes | D32 |

---

## Entries

### 1. Plan location

- **Question:** Where should `/plans/ordelo-agg-plan-cc.md` live? OrdeloAgent is on `release/ordelo-agg` and uses `.plans/`; restaurant-agents has `plans/`; no repo has a top-level `plans/`.
- **Options:**
  - ★ OrdeloAgent/plans/
  - OrdeloAgent/.plans/
  - restaurant-frontend/plans/
- **Answer:** "OrdeloAgent/plans/ (Recommended)"
- **Applied:** the plan is saved at `OrdeloAgent/plans/ordelo-agg-plan-cc.md`.

### 2. Payment microservice ownership

- **Question:** The payment microservice (Stripe wrapper at `/threads/{thread_id}/orders/{order_id}/payment-url`) isn't in any connected repo. Can you change its URL shape, return URLs, webhook signing and idempotency keys?
- **Options:**
  - ★ Yes, we own it
  - Own it, but freeze for now
  - Third party / can't change
- **Answer:** "Yes, we own it (Recommended)"
- **Applied:** D2. The payment-service changes are in release R2 (plan §9.3): return URLs, phone collection, idempotency key and signed forwards.

### 3. WhatsApp number for web customers

- **Question:** Which WhatsApp number should web customers opt into for order updates?
- **Options:**
  - ★ New Ordelo customer number
  - Reuse the Ordelo rider/admin number
  - The restaurant's own number
- **Answer:** "New Ordelo customer number (Recommended)"
- **Applied:** D3. A new Ordelo-branded customer WABA, separate from the rider/admin and per-restaurant numbers.

### 4. Where ordelo-agg-agent lives

- **Question:** Where should ordelo-agg-agent (the later WhatsApp counterpart) live?
- **Options:**
  - ★ New app in restaurant-agents
  - Inside OrdeloAgent
  - A separate new repo or service
- **Answer:** "New app in restaurant-agents (Recommended)"
- **Applied:** D4. `restaurant-agents/apps/ordelo_agg` in R4. The plan flags that a restaurant-agents ADR is needed because the app has no restaurant `rest_ref` (open question Q1).

### 5. Phone verification at guest checkout

- **Question:** Should web checkout verify the phone (OTP) before payment?
- **Options:**
  - ★ Required, not verified
  - OTP via SMS
  - OTP via WhatsApp template
- **Answer (verbatim):** "I am using stripe for payment, I do not want to verify the phone etc. Go with whats happening today, which is not OTP, just a payment checkout page."
- **Applied:** D5. No OTP; Stripe Checkout is the only gate.
- **Note:** this answer set up the clarifications in #16–#18. The phone is collected by Stripe, not by a web form.

### 6. Guest access to the order page

- **Question:** How should a guest get back to their order page after closing the tab or switching device? The order number alone mustn't unlock personal data.
- **Options:**
  - ★ Secret link + lookup fallback
  - Secret link only
  - Order number + phone
- **Answer:** "Secret link + lookup fallback (Recommended)"
- **Applied:** D6 and plan §16. A 128-bit+ token is stored hashed and exchanged for an HttpOnly cookie via `/o/{token}`. Order number + phone is a rate-limited, status-only lookup.

### 7. When the customer chooses delivery or collection, and gives a postcode

- **Question:** When should the customer choose delivery vs collection, and give a postcode?
- **Options:**
  - ★ Town page toggle + optional postcode
  - On the restaurant page
  - Postcode gate on landing
- **Answer:** "Postcode gate on landing" — **Override**
- **Applied:** D7 and plan §8. The landing page asks for a postcode, with a "Collecting instead? Choose your town" path. The postcode goes in a cookie, never in the URL.

### 8. How Ordelo gets authoritative prices

- **Question:** Today the browser decides item prices, discounts and vouchers. How should Ordelo get authoritative prices?
- **Options:**
  - ★ Ordelo reprices from the menu source
  - Web-only server repricing
  - Keep client prices + tolerance check
- **Answer (verbatim):** "There is no reprice. The prices in _menu table is authoritative."
- **Applied:** superseded by #9.

### 9. Where discounts, thresholds and vouchers live (and prices)

- **Question:** Discounts, collection thresholds and voucher codes live in the frontend's `config/restaurants.ts`, and the codes are readable in the public JS bundle. Where should those rules live?
- **Options:**
  - ★ DB offers table, applied by Ordelo
  - Keep in frontend config
  - Ordelo config file
- **Answer (verbatim):** "wait, for prices, use what is there on the UI today. Do not make any changes. Similarly, keep the config, discounts, threshoulds and voucher where they curretnly are. Mark to move them at a later point, later implementation." — **Override**
- **Applied:** D8. Prices, discounts, thresholds and vouchers stay client-side exactly as today. Moving them server-side is R5. The plan records this as an accepted risk (plan §3 F2, §11) and adds a nightly price-floor monitor as a non-invasive check.

### 10. Web `thread_id`

- **Question:** `thread_id` is NOT NULL on `food_order` and part of the payment-service path. What should a web order carry?
- **Options:**
  - ★ Checkout session id as thread_id (no thread row)
  - Change the contracts now
  - Create a real thread row
- **Answer (verbatim):** "Create a real thread maybe? but receipient as web. In doing this, we can bring the customer inthe WA agent flow, then update the recipient in threads folder. It also helps with capturing the number of sessions and metadata around the site visitors. What do you think?" — **Override**
- **Response given:** agreed, with one change. A literal `recipient='web'` would make every visitor share one recipient, so `get_active_thread(…,'web')` would return a stranger's thread. Proposed instead: `agent='WEB'`, `thread_id='WEB-<uuid>'`, `recipient=NULL`, created once at checkout start, plus a `web_session_meta` side table for UTM, device and referrer.
- **Applied:** D9 and plan §4. The web thread is the checkout/payment correlation key and the "sessions" metric. It is created with the existing `create_thread('WEB', NULL)`.

### 11. On WhatsApp opt-in: re-key or link the web thread

- **Question:** On WhatsApp opt-in, should we re-key the web thread or link it to a WhatsApp thread?
- **Options:**
  - ★ Link, don't re-key
  - Re-key the web thread
  - No thread; checkout_session table
- **Answer:** "Link, don't re-key (Recommended)"
- **Applied:** D9. On bind, ordelo_agg does `get_or_create_thread('ORDELO_AGG', phone)`, and the link is stored (`web_customer_link`, subscription). The order stays `origin_channel='web'`.
- **Note:** this refines #10's "update the recipient in threads". The recipient is not rewritten.

### 12. Where web delivery addresses live

- **Question:** Pricing and `init_delivery()` read the address from `customer_master` by phone. A mistyped phone could overwrite someone's saved WhatsApp address, and concurrent orders could race. How should web orders carry the address?
- **Options:**
  - ★ Snapshot on the order
  - Upsert customer_master (as today)
  - Snapshot for both channels now
- **Answer:** "Upsert customer_master (as today)" — **Override**
- **Applied:** D10. `capture-address` is reused unchanged.
- **Note:** once #17/#18 introduced a synthetic web customer key (W-id, one per checkout), the overwrite and race risks no longer apply to web. The upsert targets a W-id row, never a real phone. That consequence is derived in the plan (§4); it wasn't separately confirmed.

### 13. Web collection pickup time

- **Question:** The configured auto-accept path already computes now + the restaurant's pickup minutes (ADR-0001). What exactly should web collection do?
- **Options:**
  - ★ ASAP, auto-accepted, adjustable
  - Customer picks a slot
  - Follow the restaurant setting
- **Answer (verbatim):** "How about we do the same thing as the WhatsApp flow which is the order page will contain the pick up item and we can ask the customer to refer to the order page for updates on the pick up time and when the pick up time is updated the order paid reflects that pick up time look up the pick up time flow in the in the delivery hooks or the takeaway hooks you will get an idea" — **Override**
- **Interpretation (confirmed in the next question):** web collection uses the same restaurant confirmation flow as WhatsApp; there's no forced auto-accept. The order page shows "Waiting for restaurant" until `takeaway_summary.pickup_time` is set, then shows the time and any updates (`pickup_time_updated_hook` / `restaurant_pickuptime_adjusted`).
- **Applied:** D13 and plan §12.

### 14. Customer self-cancel

- **Question:** Can a web customer cancel from the order page?
- **Options:**
  - ★ No self-cancel; call the restaurant
  - Self-cancel before acceptance
- **Answer:** "No self-cancel; call restaurant (Recommended)"
- **Applied:** D14. The order page has a prominent restaurant phone. Self-cancel is later (R5).

### 15. Town membership and slugs

- **Question:** `restaurant_master` has no town and the web restaurant list comes from `config/restaurants.ts`. Where should town membership and slugs live?
- **Options:**
  - ★ Frontend config for now
  - DB table now
- **Answer:** "Frontend config for now (Recommended)"
- **Applied:** D18. `TOWNS` registry + `slug`, `towns[]`, `contactPhone`, `webOrderingEnabled` and `previousSlugs` go in `RestaurantConfig`. A DB storefront is R5.

### 16. WhatsApp sender's number ≠ checkout phone

- **Question:** If the WhatsApp sender's number differs from the phone given at checkout (a partner, or a typo)?
- **Options:**
  - ★ Allow; status-only
  - Reject mismatches
  - Allow with full detail
- **Answer (verbatim):** "Allow status only, but I do not understand what the phone number at checkout means like I mentioned the checkout is stripe and the checkout phone number is a strip thing and not the web thing"
- **Applied:** D16. A mismatched sender gets status only (no address, hand-off code or totals). "Checkout phone" now means **the phone Stripe collects**, stored as `food_order.contact_phone`.
- **Note:** the clarification led to #17.

### 17. Where the web customer's phone comes from

- **Question:** Today the phone (recipient) must exist before Stripe opens: order numbers derive from it, `capture-address` keys on it, and pricing reads the address by it. Where does the web customer enter their phone?
- **Options:**
  - ★ A web details step before Stripe
  - Stripe only (needs contract changes)
- **Answer (verbatim):** "Okay, that case we need to remove the dependency on phone number for creating order a phone number available then use it otherwise it will be random. This will be change in Ordelo service." — **Override**
- **Applied:** D12 and plan §5.2 M1. Order references are phone-derived when a 12-digit recipient exists (WhatsApp behaviour unchanged) and random otherwise, with a retry on collision. The web form has no phone field.

### 18. Web customer key before payment

- **Question:** Proposal: web gets a synthetic `cust_id` = `W` + 11 random base32 chars (fits VARCHAR(12), can't collide with a real number). `capture-address` upserts `customer_master` with it. Stripe collects name and phone (required). The payment service forwards them, and Ordelo stores them on the order before `init_delivery`. OK?
- **Options:**
  - ★ Yes, synthetic W-id + Stripe phone
  - Use the web thread_id as cust_id
  - Phone optional in Stripe
- **Answer:** "Yes, synthetic W-id + Stripe phone (Recommended)"
- **Applied:**
  - D10, D11.
  - New `food_order.contact_name/contact_phone/contact_email`.
  - `delivery_summary`/`takeaway_summary.customer_phone`, so the rider contact card and restaurant get a callable number.
  - W-id `customer_master.cust_name` is updated from Stripe before init.

### 19. Channel schema

- **Question:** Separate three facts instead of one "channel" column:
  - `food_order.origin_channel` (immutable)
  - fulfilment = the existing `food_order.action`
  - `order_notification_subscription`, plus an append-only `order_customer_event` behind one Ordelo customer-notifier module (WhatsApp-origin orders auto-subscribe to their restaurant app)
- **Options:**
  - ★ Yes, that schema
  - Just `food_order.channel`
  - Channel on the thread table
- **Answer:** "Yes, that schema (Recommended)"
- **Applied:** D15 and plan §5.2 M3, §6. The plan adds `notification_outbox` (delivery retries) and `payment_event` (idempotent inbox and outcome log) as supporting tables.

### 20. Pay-at-restaurant on web

- **Question:** For web collection orders, should pay-at-restaurant be offered?
- **Options:**
  - ★ Online payment only on web
  - Follow `takeawayPayment`
- **Answer:** "Online payment only on web (Recommended)"
- **Applied:** D17. Web collection always uses Stripe manual capture (ADR-0002). Pay-at-restaurant stays WhatsApp-only.

### 21. Release order

- **Question:** Proposed:
  - R0: web UI on fixtures
  - R1: Ordelo hardening, safe for WhatsApp
  - R2: payment service contract
  - R3: web live behind a flag, one restaurant
  - R4: WhatsApp hand-off via ordelo_agg
  - R5: the later list
- **Options:**
  - ★ Yes, R0–R5 as proposed
  - Merge R1+R2
  - WhatsApp hand-off before web live
- **Answer:** "Yes, R0–R5 as proposed (Recommended)"
- **Applied:** D19 and plan §18.

### 22. Shared-understanding check

- **Question:** A summary of all the above. Proceed to write the plan?
- **Answer:** "Yes, write the plan"
- **Applied:** plan written 2026-09-29.

---

### 23. Impact of R0 and R1 on existing services (2026-09-30)

- **Question from owner:** "R0 … and R1 … These 2 releases shouldnt have any imapct on the existing services correct? both on the UI and the Ordelo service."
- **Answer given:** R0 has none if it stays on a preview branch, and it's safe to merge if four guardrails hold:
  - the root-route clash with `app/page.tsx`;
  - shared components left unmodified;
  - the flag defaulting to off;
  - preview-only `noindex`.

  R1 is designed to be behaviour-preserving, but it rewrites live WhatsApp code paths. Seven guardrails keep it neutral: zero retries to restaurant apps, an alert-only reconciler scoped to new orders, a notifier fallback, signature `log` mode, checking manual use of `/payment-complete-test`, release notes, and a staged flag rollout.
- **Applied:** guardrails added to plan §18, R0 and R1.

### 24. Same page for WhatsApp and web? (2026-09-30)

- **Question from owner:** "On the UI I want essentially the same page that the WhatsApp currently loads to be loaded in /town/rest-ref … it has to be the same exact page for both WhatsApp and Webflow." Then: "Give me the advantages and disadvantages of having the same page … there will be lots of things like separate discounts coupon code … at some point, these UI may diverge, but I want a good design to handle this case as well."
- **Answer given:** share the building blocks, not the page. Two axes vary: **storefront** (who sells: offers, vouchers, branding, commission) and **channel** (how the customer arrived: session, address, checkout, post-payment). The recommended design has shared leaf components, one offers resolver keyed by storefront, a channel-session adapter with two implementations, and thin route shells. A new `food_order.storefront` column was suggested.

### 25. Ordelo storefront has two entry channels (2026-09-30)

- **Owner's statement (verbatim):** "Ordelo-agg (for ordelo aggregator) - entry channels are a. Web and b. whatsapp (ordelo-agg-agent). Both should have the same page elements, offers, etc"
- **Applied:** D20. One Ordelo page at `/town/{town}/{rest_ref}` for both Ordelo channels, with separate `ordeloOffers`. **Scope change:** `ordelo-agg-agent` becomes an ordering entry that sends a signed link to the same page, not only a tracker. The agent still has no order or payment tools. Plan §8.1, §14.3 and R4 were updated.

### 26. Restaurant-specific UI (2026-09-30)

- **Owner's statement (verbatim):** "Restaurant specific UI. This is not decided yet, it could be same as 1 or different. Given the magnitude of the change, what do you suggest I go with? I can take this up later, but make a note in the plan for later implementation. Do you agree?"
- **Answer given:** agreed to defer. Build only the Ordelo storefront now. Leave `/restaurant/[id]`, `MenuContainer` and `BasketDrawer` untouched, and accept time-boxed duplication of container logic. Decide later between converging onto the shared shell and staying separate with shared leaf blocks, using the triggers in plan §8.1.
- **Applied:** D21, R5 note, Q12. `food_order.storefront` is recommended for R1 but not yet confirmed (Q11).

### 27. Relax "web orders never reach restaurant apps"? (2026-10-01)

- **Question from owner:** "For a web order that would be a W-id, and the plan says that endpoint must never get web orders. - can we relax this requirement?"
- **Answer given:** it can be relaxed, but that moves work into all three restaurant-agents apps across the 10 restaurant-app hooks, and a W-id reaching them either errors, creates orphan graph state for a "customer" who never wrote, or fails to send WhatsApp messages. Keeping it is one check in Ordelo's notifier.
- **Answer (verbatim):** "Okay, let's agree to keep the rule"
- **Applied:** D27; ADR-0003.

### 28. Payment-service changes for web (2026-10-01)

- **Questions from owner:** "in the current plan, can you tell me fi the payment service should be changed?" then "Can I instead handle web and whatsapp logiic inside payment-complete ? since food_order = FoodOrder(**response.data[0]) FoodOrder will now contain where the order originated from?"
- **Recommendation given:** after reading the payment service (`58158ca`), per-order return URLs, a web session expiry, an optional idempotency key and a fail-closed `restRef` check in the payment service; signature checking in Ordelo.
- **Answer (verbatim):** "Okay, the surface area for this is too big compared to just changing order low payments complete path. Can you review that option again, please? It's okay if non-WhatsApp payment calls are made to payment complete because payment complete is the one that is called by Stripe directly. Why not just maintain rest of the services as per the existing contract and only change order the service which I have full control over."
- **Interpretation note:** "order low" / "order the service" read as "Ordelo" / "Ordelo service" (voice transcription).
- **Applied:** D22 (supersedes D2's consequence); plan §9.3 rewritten; R2 becomes a payment-path check with no deploy; M2 branches on `origin_channel`; M6 rejects unknown `rest_ref`s (F13). ADR-0004.

### 29. Webhook signing (2026-10-01)

- **Owner's statement (verbatim):** "Also, there are no endpoint signing secret currently existing. Can you confirm that? If it's not, then I would like to have the same behavior."
- **Verified:** no code or config in OrdeloAgent or the payment service reads a Stripe webhook signing secret, `Stripe-Signature` header or `ConstructEvent`; Ordelo's env holds only `ms_stripe_*` keys. (Stripe itself issues a signing secret for every webhook endpoint in the dashboard; nothing uses it.)
- **Recommendation given:** verify `Stripe-Signature` in Ordelo. **Override.**
- **Applied:** D23. `PAYMENT_WEBHOOK_SIGNATURE_MODE`, the `/paid3100` signing change and test T7 (unsigned forward) were removed. Replays stay harmless through M2. F1 forgery recorded as an accepted risk; payment-service F11/F12 recorded as a separate track.

### 30. Name and phone on web orders (2026-10-01)

- **Question from owner (verbatim):** "Name and phone. Collect them on your own checkout form and store them on the order before payment. - Can you confirm that these are absolutely required? These are not required in the current process. Why are they required in the web workflow?"
- **Finding:** name is not required: `capture-address` stores the WhatsApp number as `cust_name` today, so a web order can store the W-id. The phone is only implicit today (the WhatsApp number is the `customer_id`); the rider's `send_customer_contact` tool sends it so a rider can call the customer.
- **Options:**
  - ★ Ask for a phone on web delivery orders only
  - Never collect
  - Ask on all web orders
- **Answer:** "Never collect" — **Override**.
- **Applied:** D24 (replaces D11); `contact_*` columns and migration 006 removed; rider tool tells the rider no number is on file; D6's lookup fallback and D16's phone match are left without a second factor → new Q14, Q15, Q16; Q7 superseded. ADR-0005.

### 31. When web payments are captured (2026-10-01)

- **Owner's statement (verbatim):** "On the manual capture, it has to be manually captured and the actual capture will occur when there is an acceptance of the job by a rider."
- **Applied:** D25. Matches the existing delivery path (`delivery_inflight_graph_init_hook` → `capture_delivery_payment`). Collection keeps ADR-0002 (capture at the pickup-time boundary). Web never uses the automatic-capture call.

### 32. Post-payment redirect gap (2026-10-01)

- **Owner's statement (verbatim):** "On the gap of redirecting after paying, leave it for a later implementation. But document it in the plan."
- **Applied:** D26; plan §13.1 (what customers see per restaurant, three fix options, option 1 recommended), `/checkout/return` marked deferred, R5 item, test T18 updated.

### 33. Glossary and ADRs (2026-10-01)

- **Owner's statement (verbatim):** "Use Grill with Docs to not Grill me but to update the ubiquitous language that has been introduced in this plan and update the ADRs, etc."
- **Applied:** `CONTEXT.md` gains a "Web ordering" section; new ADR-0003 (web orders never reach restaurant apps), ADR-0004 (existing payment-service contract, unsigned webhook), ADR-0005 (synthetic keys, no customer contact).

### 34. R1 readiness fixes (2026-10-01)

- **Recommendation given:** before R1, (1) decide Q11 now, (2) let `create_order_with_items` take `origin_channel` so R2 can create a web-style order, (3) keep the late-payment guard (Q17) out of R1.
- **Answer (verbatim):** "For the fixes, 1 - Q11, add it now. 2 - I want R2 to create web-style order. 3 - agree."
- **Applied:** D28 (storefront column in R1a), D29 (`origin_channel`/`storefront` on create-order; W-id skip in `capture-address` moved to R1a), D30 (Q17 in R3).

### 35. Split R1, one SQL file, implement after updating the plan (2026-10-01)

- **Answer (verbatim):** "Okay, please split R1A and R1B. On the migrations, just give me all of the migrations in a SQL file. I'll be running those migrations manually on the database. All of the changes that you do in ordelo service, go ahead and do it, but ONLY after updating the plan ofcourse."
- **Applied:** D30, D31; plan §18 R1a/R1b and §22 checklist. Code-dependent SQL features sit behind `ordelo_config` flags that are off when missing, so code can ship before the SQL is run.

### 36. Test payments from the restaurant UI (2026-10-01)

- **Owner's request (verbatim):** "On a certain condition, as you see, we can use Stripe URL test instead. Can we have something like this in the restaurant UI? Maybe I have a URL parameter that would say isTest3100=true, then present the test URL at the checkout Can you make that change in restaurant front end?"
- **Finding:** the payment link is chosen by Ordelo (`FoodOrder.payment_uri`), not the front end, and capture/cancel use the same property, so the choice has to be made and stored in Ordelo. Honouring the parameter for anyone would let a customer pay with Stripe's test card and receive real food.
- **Options:** ★ overwatch numbers only; secret value; test restaurants only. Pages: ★ WhatsApp page only; both pages.
- **Answers:** "I want to say 1, overwatch numbers only, but on web, the phone number isnt captured right?" and "Both pages". After confirming web orders carry no phone (D24): for web, ★ test restaurants only vs a secret value → "Lets go with Option1".
- **Applied:** D32; R1a addendum in §18.

## Items still open (from the plan, §21)

These were not decided in this session:

- **Q1:** restaurant-agents identity/ADR for `ordelo_agg`.
- **Q2:** retention periods and cookie banner.
- **Q3:** support ownership.
- **Q4:** allergen obligations for web.
- **Q5:** server-side minimum-spend check on web.
- **Q6:** Ordelo-brand marketing consent.
- ~~**Q7:** upgrade path for a mismatched phone.~~ Superseded by Q15 (2026-10-01).
- **Q8:** locking down legacy unauthenticated Ordelo routes.
- **Q9:** items that sell out after the menu loads.
- **Q10:** fix the delivery-decline path (F8) before enabling decline.
- ~~**Q11:** add `food_order.storefront` in R1?~~ Answered yes (D28).
- **Q14 (2026-10-01):** lookup fallback without a phone.
- **Q15 (2026-10-01):** hand-off detail level with no collected phone.
- **Q16 (2026-10-01):** what a rider does when a web customer can't be found.
- **Q17 (2026-10-01):** late-payment cut-off for web.
- **Q12 (new):** restaurant-specific UI, converge or stay different.
- **Q13 (new):** initial `ordeloOffers` per restaurant.
