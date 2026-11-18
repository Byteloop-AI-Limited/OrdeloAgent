# ADR 0016: Find orders by postcode and unlock by house

Status: accepted, 2026-11-17. Supersedes D6's phone fallback and Q14 in plans/ordelo-agg-plan-cc.md.

Customers can find a restaurant's web orders by the postcode they ordered for: seven days, every status, newest first, at most ten. The restaurant selector groups all web restaurants by town and defaults to the saved location's town.

Delivery uses the postcode locked at checkout start, never customer_master. Collection accepts an optional lookup postcode; previous collection orders without one cannot be found. Postcodes have one canonical form (uppercase, one space before the inward code). WhatsApp orders are excluded because their customer postcode may change; they retain private links sent in chat.

Find issues one hour status_only grants in order_access_grant. Existing verify() remains the sole authentication path; no separate ticket format. The sweep prunes grants expired for at least a day. Hourly limits: ten searches per visitor, twenty per postcode; ten unlocks per visitor, five per order. Rate identities are purpose-separated SHA-256 hashes.

House number or house name proves one found delivery order. web_house_key() strips non-alphanumeric characters and folds case. A flat alone cannot unlock. The SQL check and recovered grant insertion are atomic. Grants expire 30 days after order placement.

Detail levels:
- full: original checkout grant, saved secret link or WhatsApp link; may show the 2-digit handover code.
- recovered: address, items, charges and rider first name; never the handover code.
- status_only: no address, items, charges, notes or code.

Accepted risk: postcodes and house numbers are public. Unlock stops casual snooping, not a determined neighbour. Withholding the handover code prevents this recovery path from revealing the code needed to collect food. Customers recovering on another device must use the original device or saved link for the code, or call the restaurant; the page explains this.

The frontend sends no token to browser JavaScript. It holds status grants in a signed HttpOnly lookup cookie and recovered/full grants in order cookies. lib/web/order-access.ts is the only cookie-to-credential mapping; the backend alone decides and redacts detail levels. Unlock preserves a verified original full grant.

Database objects and tests:
| Object | Caller | Tests |
| --- | --- | --- |
| web_order_request.lookup_postcode | web_checkout.create; order_lookup | test_web_contract.py; tests/sql/test_web_order_lookup_sql.py |
| web_order_lookup; web_order_unlock; web_house_key | order_lookup.find/unlock | tests/utils_common/web_ordering/test_order_lookup.py; tests/sql/test_web_order_lookup_sql.py |
| order_access_grant.detail_level | order_access; customer_order_view; lifecycle.sweep | test_order_lookup.py; test_web_contract.py |

Owner applies SQL before deploying backend; frontend follows backend. Live migrations and drift verification remain owner-controlled.

## Reading this decision in the current workflow

A lookup lists recent matching web orders with status-only access. A delivery house match can issue recovered access, including items, charges and address. Full access can also include the customer delivery confirmation code. Collection orders without a lookup postcode remain outside discovery.
