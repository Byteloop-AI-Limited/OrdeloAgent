# Rider agent exit guards: no cancel or close after pickup, confirm before a pre-pickup cancel (plan)

Status: **implemented and live-tested on Telegram (27 Oct 2026), commit `38235d0`.** Written against the working tree after commit `d91bf6b`.
Section 10 lists what differs from this plan. Kept in the repo because code and docs point to it.
Owner decisions were taken in a grilling session on 27 Oct 2026 (section 1). **There is no SQL in this change.**
Companion: [`plans/rider-dispatch-alerts-plan.md`](rider-dispatch-alerts-plan.md) section 12 (r3). A confirmed cancel before pickup is what
re-offers the order and starts a complete new reminder cycle there.

Read first: `CLAUDE.md`, `ordelo/agents/rider_agent.py`, `ordelo/agents/rider_agent_prompt.md`,
`ordelo_datamodels/dispatch/dispatch_cancel_before_pickup.sql`, `ordelo/rider_messaging/` (port + adapters),
`channels/telegram/rider/jobs.py`, `watomation/on_callback_wa_handler.py`, `tests/ordelo/agents/test_rider_agent.py`.

---

## 0. What we are building, in one paragraph

A rider can currently cancel or close a job at any time by typing to the agent. After the food is picked up that must be impossible.
The agent refuses, keeps the thread open, tells the rider someone will be in touch soon, and alerts overwatch **every time** the rider
tries. Before pickup, "I'm done" or "close this job" must not strand the order: it becomes a cancel, which returns the order to the
dispatch queue, but only after the rider taps a confirmation button (red "Yes, cancel", green "No, keep it" on Telegram; plain buttons
on WhatsApp). One new agent tool and one new messenger-port method serve both channels.

## 1. Decisions (owner, 27 Oct 2026)

| # | Decision |
|---|---|
| X1 | After pickup: **refuse, keep the thread open, alert overwatch.** The agent says someone will be in touch soon. The job stays with the rider; no re-dispatch. |
| X2 | Enforce with **code and prompt**. The code is the authority; the prompt only makes the model not try. |
| X3 | Alert overwatch **on every attempt**. No once-per-dispatch flag, no stored mark. |
| X4 | Closing a job before pickup (still `assigned`) is not allowed as a plain close. It is treated as a cancel, which puts the order back in the dispatch queue. |
| X5 | The cancel needs a **button confirmation** (red cancel, green keep). **Only a tap confirms**; typed "yes" never does. |
| X6 | **One shared tool and one port method for WhatsApp and Telegram.** WhatsApp's existing buttons are untouched. |
| X7 | Two plan documents: this one, and section 12 of the alerts plan. |

## 2. Facts this design depends on (verified in code)

- `dispatch_cancel_before_pickup(p_dispatch_id)` (`ordelo_datamodels/dispatch/dispatch_cancel_before_pickup.sql`) only works while
  `delivery_dispatch.status = 'assigned'`. Otherwise it returns the text `cannot cancel; dispatch status is <status>` (or
  `dispatch not found`). On success it marks the dispatch `declined`, deletes the other dispatches and details, and reopens the order
  with `redispatch_dtts = NOW()`.
- **The bug.** `cancel_delivery_before_pickup` (`ordelo/agents/rider_agent.py`, about lines 925-996) calls the RPC and **ignores its return
  value**. It then sets `awaiting_cancel_reason = True` and tells the rider "I have cancelled this job for you", even when the database
  refused. `agent_node` (about lines 1339-1365) then forces `terminate_delivery_job` on the rider's next message.
- `terminate_delivery_job` (about lines 1233-1281) has **no guard at all**: it closes the rider's thread (`_close_own_thread`), says
  "Delivery job completed ✅" and ends. Before pickup that strands an `assigned` order (the rider's pickup reminders keep running, nobody
  re-dispatches). After pickup it leaves a picked-up order with no rider thread.
- The prompt (`ordelo/agents/rider_agent_prompt.md`, lines 25-28 and 49-50) says "use cancel only when the rider cannot continue before a
  successful restaurant confirmation" and "then close the job". It does not mention pickup for `terminate_delivery_job`.
- `verify_restaurant_confirmation_code` (about line 780-870) sets the dispatch to `pickedup` (line 865). The live status in
  `delivery_dispatch` is the authority; `is_restaurant_confirmation_code_verified` in the graph state is a copy that can be stale.
- Neither channel's job card has a Cancel button (three buttons: Pickup Location, Dropoff Location, Contact Customer;
  `ordelo/rider_messaging/models.py` `JOB_CARD_ACTIONS`). A rider cancels only by typing to the agent.
- Button taps already reach the agent as fixed text: Telegram `RiderJobAction` (`channels/telegram/callbacks.py` line 70) ->
  `channels/telegram/rider/jobs.py` `on_job_action` (lines 127-160) -> `run_rider_agent_w_custom_msg(..., human_msg=...)`; registered at
  `jobs.py` lines 247-248. WhatsApp: `ordelo/rider_messaging/whatsapp.py` `job_card` (lines 87-109) builds `CallbackButtonData(action="/riderLocationRequest", ...)`;
  `watomation/on_callback_wa_handler.py` `rider_request_location` (lines 95-121) runs the agent; registered in `watomation/fapp_ordelo_agent.py` (line 233).
- aiogram 3.31.0 `InlineKeyboardButton` has `style` (`'danger'` red, `'success'` green, `'primary'` blue). WhatsApp reply buttons have no colour
  (and a 20-character title limit).
- Overwatch alert: `channels/telegram/ops_alerts.py` `alert_ops(text)` (WhatsApp overwatch numbers, never raises, already used by
  `ordelo/offer_reminders.py`). `mask(phone)` in the same file.
- A turn ends silently when the last message is an `AIMessage` (`agent_node`: "If tool message replied to user already, end the turn"). The
  convention is `AIMessage("/dontRespond: ...")` after the tool has already spoken (see `terminate_delivery_job`).

## 3. Design

### 3.1 What each status means to the agent

| `delivery_dispatch.status` | Rider asks to cancel / decline / close | Result |
|---|---|---|
| `assigned` (not picked up) | `request_cancel_confirmation` | Send the two buttons. Nothing changes until a tap. |
| `pickedup` | any of the three tools | **Refuse.** Say someone will be in touch soon. `alert_ops` every time. Thread stays open. |
| `declined` (a confirmed cancel already ran), `completed`, `missed`, `unassigned`, no dispatch | `terminate_delivery_job` | Close as today. |
| status cannot be read | any | **Fail closed**: do not close or cancel, log, tell the rider to try again shortly. No alert unless it repeats (implementer's call; default none). |

### 3.2 Modules, interfaces and seams (codebase-design vocabulary)

New deep module **`ordelo/job_exit.py`**: the whole "may this rider leave this job?" decision and the refusal, behind a small interface, with
the database and the alert behind seams so tests need no network (the same shape as `ordelo/offer_reminders.py`).

```python
# ordelo/job_exit.py
class Verdict(str, Enum):
    ASK_CONFIRM = "ask_confirm"      # assigned: ask the rider to tap
    REFUSE = "refuse"                # pickedup: refuse and alert overwatch
    ALLOW_CLOSE = "allow_close"      # declined / completed / missed / unassigned / no dispatch: the thread may close
    UNKNOWN = "unknown"              # could not read the status: fail closed

def decide(status: str | None) -> Verdict: ...        # pure; the table in 3.1

class DispatchStatusStore(Protocol):                   # seam 1
    async def status(self, dispatch_id: int) -> str | None: ...   # raises on read errors
class SupabaseDispatchStatusStore: ...                 # select status from delivery_dispatch where dispatch_id = ...

AlertFn = Callable[[str], Awaitable[None]]             # seam 2: channels.telegram.ops_alerts.alert_ops

async def verdict_for(dispatch_id: int | None, store=...) -> Verdict: ...   # None -> ALLOW_CLOSE; store error -> UNKNOWN

REFUSE_TEXT = ("I can't cancel or close this job now because the food has already been picked up. "
               "I've let our team know and someone will be in touch with you soon.")

async def refuse_after_pickup(*, messenger, order_number, dispatch_id, rider_name, rider_phone, rider_words, alert=alert_ops) -> None:
    """Tell the rider (REFUSE_TEXT), then alert overwatch. Called on EVERY attempt (decision X3)."""
```

Alert text (one line, `mask()` the phone):
`⚠️ Rider tried to cancel AFTER pickup · order {order_number} · {rider_name} ({mask(phone)}) · dispatch {dispatch_id} is pickedup. Rider said: "{rider_words[:200]}". The agent refused; the job is still with the rider. Please contact them.`

Messenger port: **one new method**, mirrored on every adapter (the seam already used by `offer_job`, `job_card`, `delete`):

```python
# ordelo/rider_messaging/port.py
async def confirm_cancel(self, dispatch_id: int, token: str, text: str) -> MsgRef:
    """Ask 'Do you want to cancel this job?' with two buttons: Yes, cancel job / No, keep it. A tap reaches the rider agent as
    models.cancel_tap_text(token, 'yes'|'no'). Only a tap confirms."""
```

Shared constants in `ordelo/rider_messaging/models.py`:

```python
CANCEL_YES_TITLE = "Yes, cancel job"   # 15 chars; WhatsApp limit is 20
CANCEL_NO_TITLE = "No, keep it"
CANCEL_CONFIRM_TEXT = "Do you want to cancel this job? It will be offered to other riders and you won't be offered it again."
CANCEL_TAP_RE = re.compile(r"\[cancel-confirm:(?P<token>[0-9a-f]{8}):(?P<answer>yes|no)\]")
def cancel_tap_text(token: str, answer: Literal["yes", "no"]) -> str:
    return f"[cancel-confirm:{token}:{answer}]"
```

**Why a token.** The tap arrives as an ordinary human message. If it were a fixed phrase, a rider could type it and "confirm" without
tapping. The token is random (`secrets.token_hex(4)`), is stored only in graph state and in the buttons' callback data, so a typed message
cannot match it. That is what makes "tap is the only confirmation" (X5) true in code.

### 3.3 Graph state (`AgentState`, `ordelo/agents/rider_agent.py` lines 100-115)

Add two fields next to `awaiting_cancel_reason`:

```python
cancel_confirm_token: str | None     # set when the buttons are sent; cleared on any valid tap
cancel_confirmed: bool               # set by agent_node on a valid "yes" tap; consumed by cancel_delivery_before_pickup
```

### 3.4 Flow

1. Rider types "I'm done" / "cancel" / "decline" / "close this job". The prompt tells the model to call **`request_cancel_confirmation(rider_words)`**
   for any of these, before or after pickup.
2. `request_cancel_confirmation` calls `job_exit.verdict_for(dispatch_id)`:
   - `ASK_CONFIRM` -> `token = secrets.token_hex(4)`; `await ctx.messenger.confirm_cancel(dispatch_id, token, CANCEL_CONFIRM_TEXT)`; return
     `Command(update={"cancel_confirm_token": token, "messages": [ToolMessage(...), AIMessage("/dontRespond: cancel confirmation sent")]})`.
   - `REFUSE` -> `job_exit.refuse_after_pickup(...)`; same `ToolMessage` + `/dontRespond` `AIMessage`. Thread stays open. No state change.
   - `ALLOW_CLOSE` -> `ToolMessage("There is no open job to cancel.")`; the model replies normally.
   - `UNKNOWN` -> `ToolMessage("I couldn't check the job right now; ask the rider to try again in a minute.")` plus a `logger.error`.
3. Rider taps a button. Telegram `RiderCancelConfirm` / WhatsApp `/riderCancelConfirm` callback runs the agent with
   `human_msg = cancel_tap_text(token, answer)` (section 5.4, 5.5).
4. New first branch in `agent_node` (before the `awaiting_cancel_reason` branches, because the token must be handled before the model sees the message):
   - `HumanMessage` matches `CANCEL_TAP_RE` **and** token equals `state["cancel_confirm_token"]`:
     - `yes` -> update `{"cancel_confirm_token": None, "cancel_confirmed": True}` and emit a synthetic `AIMessage` tool call to
       `cancel_delivery_before_pickup`, `goto="toolNode"`. (Deterministic: the model does not decide.)
     - `no`  -> update `{"cancel_confirm_token": None}`, `AIMessage("Okay, the job stays with you.")`, `goto="respondNode"`.
   - matches the pattern but the token differs or is unset (stale button) -> `AIMessage("That button has expired. Tell me again if you want to cancel.")`, `goto="respondNode"`.
   - token is set and the rider typed something else -> synthetic `request_cancel_confirmation` tool call (a new token invalidates the old buttons) with
     the text "Please tap one of the buttons to confirm or keep the job." (decision X5: typed text never confirms). *Trade-off accepted:* a rider who asks an unrelated question while a confirmation is open gets the buttons again until he taps No.
5. `cancel_delivery_before_pickup` (guarded, section 5.2) calls the RPC. Success -> existing behaviour: `awaiting_cancel_reason = True`, asks for the reason; the next
   message becomes `terminate_delivery_job(reason)`, which closes the thread because the dispatch is now `declined`.
6. The order is back in the dispatch queue. Other riders get fresh offers with a complete new reminder cycle (alerts plan section 12).

## 4. Why the guards are in the tools as well as in `request_cancel_confirmation`

The model may call `cancel_delivery_before_pickup` or `terminate_delivery_job` directly, and `agent_node` itself forces `terminate_delivery_job`.
Each tool therefore re-checks on its own (defence in depth); a prompt mistake or a hallucinated call cannot strand or abandon a job.

## 5. Changes, file by file

### 5.1 New `ordelo/job_exit.py` (section 3.2) and `ordelo/rider_messaging/models.py` constants

Create `job_exit.py` as above. Add the constants and `cancel_tap_text` to `models.py`, export them from `ordelo/rider_messaging/__init__.py`
(next to `JOB_CARD_ACTIONS`, line 13/32).

### 5.2 `ordelo/agents/rider_agent.py`

```python
# AgentState: + cancel_confirm_token: str | None ; cancel_confirmed: bool

@tool  # via the existing `rider_agent_tools = [tool(service) for service in _rider_agent_tools]` list
async def request_cancel_confirmation(rider_words: str, state, tool_call_id, runtime) -> Command: ...   # 3.4 step 2
```

`cancel_delivery_before_pickup` (replace the body's start and the RPC handling):

```python
    if not state.get("cancel_confirmed"):
        return Command(update={"messages": [ToolMessage(
            "Not confirmed. Call request_cancel_confirmation; only the rider's button tap can cancel a job.", tool_call_id=tool_call_id)]})
    ...
    res = client_ordelo.rpc("dispatch_cancel_before_pickup", {"p_dispatch_id": dispatch_id}).execute()
    reply = res.data if isinstance(res.data, str) else ""
    if reply.startswith(("cannot cancel", "dispatch not found")):
        # the database refused: never tell the rider it worked
        verdict = await job_exit.verdict_for(dispatch_id)
        update = {"cancel_confirmed": False, "messages": [ToolMessage(...)]}
        if verdict is job_exit.Verdict.REFUSE:
            await job_exit.refuse_after_pickup(...)       # alert on every attempt
            update["messages"].append(AIMessage("/dontRespond: cancel refused after pickup"))
        return Command(update=update)
    # success: existing code, plus "cancel_confirmed": False in the update
```

`terminate_delivery_job` (insert before `_close_own_thread`):

```python
    verdict = await job_exit.verdict_for(dispatch_id)
    if verdict is Verdict.ASK_CONFIRM:          # assigned: a plain close would strand the order -> same as request_cancel_confirmation
        return await _ask_cancel_confirmation(...)     # shared helper with request_cancel_confirmation
    if verdict is Verdict.REFUSE:
        await job_exit.refuse_after_pickup(...)
        return Command(update={"messages": [ToolMessage("Refused: food already picked up; overwatch alerted.", ...), AIMessage("/dontRespond: close refused after pickup")]})
    if verdict is Verdict.UNKNOWN:
        return Command(update={"messages": [ToolMessage("Could not check the job; not closed.", ...)]})
    # ALLOW_CLOSE: existing behaviour unchanged
```

The forced `terminate_delivery_job` in `agent_node` (awaiting_cancel_reason) is fine: the status is `declined` after a confirmed cancel, so the verdict is `ALLOW_CLOSE`.
Add `request_cancel_confirmation` to `_rider_agent_tools` (about line 1292). Update the module docstring tool list (about line 26).
`rider_words` for the alert is the tool argument; for the guarded direct calls use the last human message in `state["messages"]`.

### 5.3 `ordelo/agents/rider_agent_prompt.md`

Replace the `cancel_delivery_before_pickup` and `terminate_delivery_job` bullets (lines 25-28) and journey step 5 (lines 49-50):

```
- `request_cancel_confirmation`: call this whenever the rider says they want to cancel, decline, give up, stop or close the job,
  before or after pickup. Pass the rider's own words. It decides what happens; do not decide yourself and do not promise anything.
  Before pickup it shows the rider two buttons. After pickup it refuses and alerts the team. Never ask "are you sure" in text.
- `cancel_delivery_before_pickup`: you cannot call this yourself unless the rider has just tapped "Yes, cancel job". Never call it otherwise.
- `terminate_delivery_job`: close the rider thread only after a confirmed cancel has been recorded or the delivery is complete.
  A job that is picked up can never be cancelled or closed by the rider.

## Leaving a job
- Before pickup: if the rider wants out, call `request_cancel_confirmation`. Wait for the tap. A typed "yes" does not count.
- After pickup (restaurant code verified): the rider must deliver. Do not offer to cancel, do not suggest alternatives, do not
  say it is possible. Call `request_cancel_confirmation`; it will say that someone will be in touch.
```

Journey step 5 becomes: `5. If the rider wants to cancel or close the job, call request_cancel_confirmation (see "Leaving a job").`

### 5.4 Telegram

- `channels/telegram/callbacks.py` (after `RiderJobAction`, line 70):

```python
class RiderCancelConfirm(CallbackData, prefix="rc1"):
    """Yes (y) or No (n) under 'Do you want to cancel this job?', e.g. 'rc1:84217:ab12cd34:y' (fits the 64-byte limit).
    t is the random token the agent put in its graph state; the handler only checks the dispatch belongs to the tapping rider."""
    d: int
    t: str
    a: Literal["y", "n"]
```

- `channels/telegram/keyboards.py` (next to `rider_job_card_kb`, line 81):

```python
def rider_cancel_confirm_kb(dispatch_id: int, token: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=CANCEL_YES_TITLE, callback_data=RiderCancelConfirm(d=dispatch_id, t=token, a="y").pack(), style="danger")
    b.button(text=CANCEL_NO_TITLE, callback_data=RiderCancelConfirm(d=dispatch_id, t=token, a="n").pack(), style="success")
    b.adjust(2)
    return b.as_markup()
```

- `ordelo/rider_messaging/telegram.py`: `confirm_cancel` = `send_message(self.tcid, f"<b>Cancel this job?</b>\n{text}", reply_markup=rider_cancel_confirm_kb(dispatch_id, token))`; return `tg_ref`.
- `channels/telegram/rider/jobs.py`: `on_cancel_confirm(query, callback_data: RiderCancelConfirm, ...)`, same checks as `_handle_job_action` (rider linked, thread belongs to rider, thread active and not completed;
  factor the shared lookup into one helper rather than copying), then edit the confirmation message to remove the buttons (`edit_reply_markup(None)`; avoids double taps), and
  `spawn(run_rider_agent_w_custom_msg(recipient=rider_id, human_msg=cancel_tap_text(callback_data.t, "yes" if callback_data.a == "y" else "no"), thread_id=thread.thread_id), "cancel confirm ...")`.
  Register next to line 248: `router.callback_query.register(on_cancel_confirm, RiderCancelConfirm.filter())`.

### 5.5 WhatsApp

- `ordelo/rider_messaging/whatsapp.py`: `confirm_cancel` builds two `Button`s (titles `CANCEL_YES_TITLE`, `CANCEL_NO_TITLE`, no colour available) whose `callback_data` is
  `CallbackButtonData(action="/riderCancelConfirm", recipient=self.phone, dispatch_id=dispatch_id, human_msg=cancel_tap_text(token, "yes"|"no"), ai_msg="", response="").model_dump_json()`,
  sent like `job_card` (lines 87-109) with `text=CANCEL_CONFIRM_TEXT`. Do **not** include `/riderLocationRequest` in the action string (that filter is `contains`).
- `watomation/on_callback_wa_handler.py`: `IS_CANCEL_CONFIRM = filters.contains("/riderCancelConfirm", ignore_case=False)` and `rider_cancel_confirm(wa, msg)`, a copy of `rider_request_location`
  (lines 98-121) including the "This job is expired." branch for a completed dispatch. Register it beside line 233 in `watomation/fapp_ordelo_agent.py`
  (import near line 97).
- `ordelo/rider_messaging/fake.py`: record `confirm_cancel` calls (for tests).

### 5.6 Docs

- `ordelo/agents/rider_agent.py` header docstring: tool list and the new rules.
- `CONTEXT.md`: add **Cancel confirmation** (token + tap) and **Post-pickup refusal**.
- `docs/delivery_process.md` phase 6 (deliver): "a rider cannot cancel or close after pickup; the agent refuses and overwatch is alerted on every attempt; before pickup a cancel needs a button tap".
- `docs/to-do.md`: add "WhatsApp and Telegram job cards have no Cancel button; cancel is by typing only" (not in this change).
- No SQL standard, catalog or guide changes (no SQL).

## 6. Tests (all offline; no database, no network)

- `tests/ordelo/test_job_exit.py`: `decide()` over every status (`assigned`, `pickedup`, `declined`, `completed`, `missed`, `unassigned`, `None`); `verdict_for(None)` is `ALLOW_CLOSE`;
  a store that raises gives `UNKNOWN`; `refuse_after_pickup` sends `REFUSE_TEXT` and calls the alert **once per call** (three calls -> three alerts); alert text contains order, masked phone, quoted words; an alert that raises does not stop the rider message.
- `tests/ordelo/agents/test_rider_agent.py` (existing file; update `test_cancel_delivery_before_pickup_calls_rpc_and_sets_awaiting_reason` to put `cancel_confirmed: True` in the state):
  - cancel without `cancel_confirmed` -> no RPC call, a "not confirmed" tool message;
  - cancel with confirmation and RPC reply `cannot cancel; dispatch status is pickedup` -> `awaiting_cancel_reason` not set, rider NOT told it was cancelled, alert sent, `cancel_confirmed` reset;
  - cancel with confirmation and RPC `dispatch not found` -> not told it worked;
  - `terminate_delivery_job` with status `assigned` -> confirmation buttons sent, thread NOT closed, no "completed ✅";
  - `terminate_delivery_job` with `pickedup` -> refusal text, alert, thread NOT closed;
  - `terminate_delivery_job` with `declined` and `completed` -> closes as today (update the existing `test_terminate_delivery_job_records_cancel_reason_and_closes_thread`);
  - `terminate_delivery_job` when the status read raises -> not closed (fail closed);
  - `request_cancel_confirmation` for `assigned` / `pickedup` / `completed` / unreadable;
  - `agent_node`: valid `yes` token -> synthetic `cancel_delivery_before_pickup` call and `cancel_confirmed` true; `no` -> token cleared, job stays; wrong or stale token -> "button expired"; typed text with a token set -> new confirmation, **never** a cancel; a typed `[cancel-confirm:<guessed token>:yes]` does not match the stored token, so it gets the "button expired" reply (the rider never sees the token, so he cannot type a valid one).
  - keep the existing `test_agent_node_routes_awaiting_cancel_reason_tool_and_human_messages`.
- `tests/ordelo/rider_messaging/` (follow the existing adapter tests): `FakeRiderMessenger.confirm_cancel`; Telegram adapter sends the keyboard with `style` `danger` / `success` and `callback_data` <= 64 bytes; WhatsApp adapter titles <= 20 chars and callback JSON has action `/riderCancelConfirm`, the token and `human_msg`; the port Protocol conformance test lists the new method.
- `tests/channels/telegram/test_rider_jobs.py` (pattern at line 192): `on_cancel_confirm` rejects an unlinked rider, someone else's dispatch, an inactive/completed thread; a valid tap removes the buttons and spawns the agent with `cancel_tap_text(token, "yes"|"no")`.
- WhatsApp callback test (pattern of the existing `rider_request_location` test): completed dispatch -> "This job is expired."; otherwise the agent is run with the callback's `human_msg`.
- Prompt: no snapshot test; add `tests/ordelo/agents/test_rider_agent_prompt.py` asserting the prompt names `request_cancel_confirmation` and does not tell the model to call `cancel_delivery_before_pickup` itself.
- Run: `pytest tests/ordelo tests/channels tests/watomation`, `ruff check .`. **WhatsApp regression focus:** `pytest tests -k "rider and (whatsapp or wa_ or callback)"` must be unchanged apart from the cancel/terminate tests above.

## 7. Live test (STRK; no SQL changes; use the existing `test_restaurant_notices.sql` stages to create, offer and accept the order)

Telegram rider first, then repeat on a WhatsApp rider:
1. Accept a STRK order (STAGE 1 / 2b). Before pickup type "I'm done". Expect: a message with a red **Yes, cancel job** and a green **No, keep it** (WhatsApp: two plain buttons).
2. Type "yes". Expect: the buttons again, nothing cancelled. Tap **No**. Expect: "Okay, the job stays with you."; the job continues.
3. Type "close this job", tap **Yes**. Expect: "I have cancelled this job for you" and the reason question; after the reason, the thread closes. The order is re-offered: other riders get fresh offers with reminders from 1 of 7 (alerts plan 12.6 step g; re-run STAGE 2b).
4. New accepted order; enter the restaurant code (picked up). Type "cancel the order", then "I don't want to do this" and "close it". Expect each time: the refusal with "someone will be in touch with you soon", **one overwatch alert per attempt** (three alerts), the thread still open, `delivery_dispatch.status` still `pickedup`. Tap an old button from step 1 if still on screen: expect the refusal / "expired".
5. Deliver with the customer code; the thread closes normally.

## 8. Rollout

No SQL, no migration, no config. Deploy the app (single PR). Order is irrelevant to the alerts plan; the two plans can ship separately.
Rollback: revert the PR. State fields are additive; an in-flight thread without them behaves as before.

## 9. Not in this change

- A real "abort after pickup" workflow for ops (tools to reassign a picked-up order, refund and food handling). The agent only refuses and alerts.
- A Cancel button on the job card (cancel stays a typed request; see `docs/to-do.md`).
- Rate-limiting overwatch alerts (X3: every attempt alerts). If it becomes noisy, add a per-dispatch cool-down inside `job_exit.refuse_after_pickup`; the call site does not change.
- Any change to the SQL `dispatch_cancel_before_pickup()` (its status guard is correct and stays).

## 10. Implementation notes (what was built, and how it differs from this plan)

- Built as planned: `ordelo/job_exit.py` (verdicts, status store seam, `refuse_after_pickup`), `request_cancel_confirmation`, guards in
  `cancel_delivery_before_pickup` and `terminate_delivery_job`, `confirm_cancel` on the messenger port (Telegram red/green buttons, WhatsApp plain
  buttons), Telegram `RiderCancelConfirm` callback and WhatsApp `/riderCancelConfirm` callback, prompt update.
- **Trusted tap flag.** Besides the random token, `run_rider_agent_w_custom_msg(..., cancel_tap=True)` marks the tap's `HumanMessage` with
  `additional_kwargs={"cancel_tap": True}` (`ordelo/agents/agent_runner.py`). Typed text can never carry that flag, so a typed marker cannot confirm.
- `job_exit.py` is smaller than sketched: no separate alert seam constant; `refuse_after_pickup(..., alert=None)` defaults to `alert_ops`.
- Alert on **every** attempt, as decided (X3).
- **Known gap (not fixed):** `dispatch_cancel_before_pickup()` checks the status and updates it in two statements, so a pickup and a cancel
  at the same instant could both succeed. Needs an atomic database transition (`docs/to-do.md`). Rare; the agent guard is the main protection.
- **Known gap:** the job cards have no Cancel button; riders cancel by typing (`docs/to-do.md`).
