---
name: verify-test-order-local-setup
description: Verify Ordelo changes end to end on the local setup (localhost behind the Cloudflare test hostnames) by placing TEST3100 orders on the Strikers web storefront, simulating payment, and acting as the owner in Telegram Web to accept, decline, choose a pickup time, mark ready, and complete the rider job. Use when asked to verify a change live, place a test order automatically, run the verification loop, or check the local test setup. For Stripe sandbox, Swagger or WhatsApp order tests use ordelo-local-automatic-orders.
---

# Verify a test order on the local setup

Run the real journey in the owner's Chrome, then prove each step three ways: what the customer or Telegram screen shows, the backend log, and a read-only database row. First proved on 25 November 2026 ([report](../../../docs/releases/verify-test-order-local-setup-2026-11-25.md)).

## Facts to hold on to

- **One database: production Supabase.** Local services, deployed services and both bots share it. While the shared URLs point at the test hosts, real restaurants' triggers also run on the local code.
- **The owner switches routing, never the agent.** `ordelo_config.ORDELO_APP_URL` = `https://rider-agent-test.ordelo.app` (localhost:3100) and `RESTAURANT_MENU_APP_URL` = `https://restaurant-test.ordelo.app` (localhost:3000). Switch and restore SQL: [runbook](../../../docs/local-testing-runbook.md) sections 5 and 7.
- **The two URLs do not move the bot webhooks.** Check `getWebhookInfo`. The table says which code your evidence covers.
- **The owner runs both servers** (uvicorn and `next dev`). Never stop or restart them. They reload on save and serve live traffic, so keep every save importable and apply SQL before code that calls it.
- **Only STRK, only `TEST3100`.** That exact item selects test payment and limits rider offers to overwatch riders. STRK's city is `dummy`, so only the owner's riders match. Two items (£19.00) clear the minimum.
- **Open the configured storefront:** `https://restaurant-test.ordelo.app/town/orpington/strk`.

| Step | Runs on the local code when |
| --- | --- |
| Storefront, checkout, tracking page, dashboard links | You are on `restaurant-test.ordelo.app` |
| Restaurant and rider hooks fired by database triggers and cron (timeout sweep, default pickup, dispatch, pickup set, alerts) | `ORDELO_APP_URL` is the test host |
| Telegram taps, commands and typed messages | That bot's webhook is `rider-agent-test.ordelo.app/telegram/...`; otherwise the **deployed** bot handles them and calls the same SQL |

If the change is in a Telegram handler and the webhook is still on production, the live run cannot verify it. Say so and ask the owner to switch the webhook.

Run cheaper evidence first, and note failures that already existed before your change:
1. offline tests (`pytest`; frontend `vitest`, `lint`, `build`)
2. isolated SQL (`ordelo-sql-test-db` skill)
3. this live run. For kitchen and rider journeys that need no storefront order, the fake `STRK-TEST-*` rows in [live-order-test-harness.md](../../../docs/live-order-test-harness.md) are lighter.

## 1. Preflight

```zsh
cd /Users/basavaraj/bloop/OrdeloAgent && source .venv/bin/activate && export PYTHONPATH="$PWD" && envLoad
SK=.claude/skills/verify-test-order-local-setup/scripts
python $SK/db_evidence.py preflight          # URLs, webhooks, STRK policy, pickup defaults, riders, open orders
agent-desktop permissions                    # accessibility must be granted; screen recording is not needed
```

- If accessibility is denied, ask the owner to run `agent-desktop permissions --guide`. Do not route around it.
- `ENABLE_SIMULATE_PAYMENT` must be `true`, and `ORDELO_APP_URL` must be the test host.
- Say whether the code under test is deployed (`git branch -r --contains <commit>`). A local pass is a rehearsal, not a production check.
- Confirm the running backend is this checkout: `lsof -a -p $(lsof -tiTCP:3100 -sTCP:LISTEN | head -1) -d cwd`, and that the code under test is in it.
- Write down the timeout minutes and action, and any setting you will change. Expected timings come from these values.

Find the server logs in the owner's Rex session `RunServices`:

```zsh
REX="/Applications/Rex.app/Contents/Helpers/Rex Server.rex/Contents/MacOS/rex"   # "Rex Beta.app" on older installs
"$REX" ls --json; "$REX" block ls -s <session> --json
"$REX" capture -s <session> -b <block> --trim    # uvicorn = backend, next dev = frontend
```

Log lines wrap at the pane width; join them (`tr -d '\n'`) before searching for a URL.

## 2. Open the windows

Leave the owner's Telegram split view alone. It can hold a second account and personal chats. Open separate windows, each holding one page:

```zsh
co() { python3 $SK/chrome_order.py "$@" }
KITCHEN=$(co open "https://web.telegram.org/k/#@OrdeloRestaurantBot")
RIDER=$(co open "https://web.telegram.org/k/#@ByteloopRidersBot")
```

The `/k/` URL without `?account=` is the first account (`lohith`: linked STRK admin and overwatch rider). Confirm recent STRK or ELAS cards are in the chat. The script refuses any chat other than these two bots. Never type in a person's chat.

### Overwatch alerts on WhatsApp Web

Overwatch alerts (ops alerts, invite-claim alerts, escalations, payment and capture warnings) go to the overwatch numbers on **WhatsApp**, not Telegram. The owner keeps `https://web.whatsapp.com/` logged in as an overwatch number, as a tab (tab title `WhatsApp`, often with an unread count) in the same Chrome window as the Telegram Web split view.

- **Only the `ByteLoop Ai` chat.** Ordelo's WhatsApp Business number shows as the contact `ByteLoop Ai`. Search for that exact name, open that chat, and read only its latest messages. Never scan the chat list, open another chat, or type, react or send anything in WhatsApp.
- **Use agent-desktop first, computer use as a fallback.** Chrome tabs appear as `radiobutton` elements: `agent-desktop find --app "Google Chrome" --role radiobutton`. WhatsApp Web runs in one tab only, so do not open a second WhatsApp window. Bring the existing tab to the front, read it, then select the tab that was active before.
- **Evidence.** Record the alert text with phone numbers masked, the time and the count (for example, one message per claim and none after a replay). Cross-check with the database row (for invite claims, `t_invites.rider_alert_result` and `rider_alert_accepted`) and the local send log. WhatsApp API acceptance proves only that the message was accepted, while the chat proves it arrived.

Start the watcher in the background and keep its log:

```zsh
nohup python $SK/db_evidence.py watch 2400 > "$SCRATCH/watch.log" 2>&1 &
```

## 3. Place the order

```zsh
read O STORE < <(co order Collection --qty 2); echo $O $STORE      # or Delivery; STORE = its tracking window
```

It sets TEST3100 to the quantity, goes to review, **stops unless the page says "This is a test order"**, then presses Simulate payment. Delivery needs a saved postcode (BR6 6DN works) and fills house number `1`.

Each call opens its own storefront window. `--review-only` stops before payment: run it twice and the same unpaid order must come back (one `food_order` row). After payment the same basket must create a new order. If a call prints an order number you already have, the checkout was reused after payment, which is a defect.

After an ambiguous result, look the order up in the database before trying again.

## 4. Act as the restaurant

```zsh
co tg-tap $KITCHEN OrdeloRestaurantBot $O 'Accept$'      # waits for the alert (about 5 s after payment)
co tg-read $KITCHEN OrdeloRestaurantBot --tail 20
```

| To check | Do | Expect |
| --- | --- | --- |
| Pickup fallback | Accept, leave the time buttons | About 15 s + one 10 s sweep later: `auto_accept`, `after_order` = default minutes |
| Explicit pickup | Accept, **wait 5 s**, then `tg-tap ... '^11:00 AM$'` before 15 s have passed | `restaurant_accept` stays; the chosen time survives the sweep |
| Decline | `'Decline$'` | `declined` / `restaurant_decline`; shared "couldn't accept" copy |
| Silence | Tap nothing; `watch-page $STORE 110` (repeat) | Countdown, "Checking with…" at zero, then `auto_decline` within one sweep; seven alerts sent |
| Ready | `'Ready'` | `ready_at` set; the rider is told (delivery) |

`watch-page` prints the tracking page's wording as it changes. Keep one call under two minutes.

## 5. Act as the rider (delivery)

```zsh
co tg-tap $RIDER ByteloopRidersBot $O 'Accept$'
python $SK/db_evidence.py order $O                             # assigned
```

1. Wait for the job card and "Thank you for accepting".
2. Read the restaurant code from the kitchen receipt and the customer code from the tracking page.
3. `tg-say $RIDER ByteloopRidersBot 'Picked up, restaurant code NN'` → dispatch `pickedup`, page "On its way".
4. `tg-say $RIDER ByteloopRidersBot 'Delivered, customer code NN'` → `completed`, page "Delivered".

To check the no-rider path, tap nothing: STRK times out after `STRK_DELIVERY_TIMEOUT_TIME` minutes. Never leave an accepted job unfinished.

## 6. Change a setting on purpose

Use the dashboard, not SQL, so the change is audited. `tg-say ... "/manage"`, press `link "Manage Strikers Sports Bar"` (**real restaurants are listed next to it**), then `OPEN`, then Actions. For a magic-link change also confirm the second tap of the same link is refused. "Use default" plus Save stores `''` (inherit). Capture the values first, restore them in the same session, and confirm with `preflight`. Only change a setting the user's task covers.

## 7. Evidence and finish

```zsh
python $SK/db_evidence.py order $O
```

For each scenario record: order number, what the page and chat showed, the log line that proves local code ran, and the row. Label evidence **offline**, **isolated database** or **live local**, and name the code that handled Telegram taps.

Limits of simulated payment:
- No PaymentIntent exists, so capture returns 500 and logs `Payment capture failed` (overwatch is alerted). This is expected. Any other `ERROR` or traceback is not.
- It proves nothing about Stripe authorisation, capture or payout. Use `ordelo-local-automatic-orders` for that.
- Test orders appear in the STRK dashboard and the nightly price audit.

Before finishing: no STRK order awaiting a decision or an inflight rider job (a collection ends at `pickup_confirmed` with `ready_at` set), settings restored, watcher stopped, your windows closed with `co close WIN` (leave the owner's), the owner's previously active Chrome tab selected again if you switched to WhatsApp, report written to `docs/releases/verify-test-order-local-setup-<date>.md`. Leave the routing as it is and remind the owner to restore it.

## When something goes wrong

| Symptom | Cause and action |
| --- | --- |
| `expected one page, found 0` | The window is behind another and stopped rendering. The script focuses it; run the command again. |
| `expected one page, found 2` | Split view. Use a separate window. |
| Chat list row does nothing | Telegram Web listens for mouse-down there. Open the chat by URL (section 2). |
| Second tap has no effect | Telegram Web drops a tap made within about 2 s of the previous one. Check `t_inbox` for the callback, wait 5 s, tap again. Accept, Decline and pickup are first-choice-wins in SQL. |
| Countdown missing from a tree | `--compact` snapshots drop it. The script does not use it. |
| `AMBIGUOUS` or `STALE_REF` | Take a fresh read. Do not repeat the old ref. |
| `retry: unsafe` on a click | Normal for a press. Confirm by reading the page or row, never by pressing again blindly. |
