# Ordelo WhatsApp inventory and Telegram mapping

Source inspection: 13 October 2026, `/Users/basavaraj/bloop/OrdeloAgent`. Source snapshot, not a live provider/database audit. Paths below are relative to that root; reread before editing. Avoid importing modules to inventory them: configuration can load secrets or initialize clients.

## Senders and receivers

| Observed interaction | Source anchors | Telegram approach |
| --- | --- | --- |
| Text, instructions, graph responses, alerts | `ordelo/agents/rider_agent.py`, tools/`respond_node`; `byteloop_agent.py`; `watomation/on_message_wa_handler.py`; `utils_common/waba_utils/wa_senders.py` | `Bot.send_message` / `Message.answer` with linked destination |
| Header/body/footer, WA bold receipts | `wa_senders.admin_order_reciept`, `takeaway_admin_order_receipt`; `utils_common/order_management/food_order_reciept.py` | Escaped HTML/entities; split large receipts while retaining order context and controls |
| Dispatch Accept/Decline, JSON `command` | `watomation/routers/delivery_hooks.py`, `wa_send_delivery_dispatch_request_to_rider`; callback `dispatch_response` | Inline keyboard + compact callback/token; reload dispatch and resolve actor to rider |
| Pickup/dropoff/contact buttons | `ordelo/agent_app_handlers.py`, `_send_delivery_instructions`; callback `rider_request_location` | Action + dispatch reference; construct graph instructions server-side, never trust payload `human_msg` |
| Restaurant Accept/Decline, pickup choices | `wa_senders.send_restaurant_order_confirmation`, `send_restaurant_pickup_time`; callback handlers | Inline keyboard; preserve delivery/takeaway branch and stale pickup-time guard |
| Food ready, +10/+20 pickup, takeaway ready | `wa_senders.admin_order_reciept`, `takeaway_admin_order_receipt`; `admin_collection_ready`, `admin_adjust_pickup_time`, `admin_takeaway_ready` | Verify restaurant actor; retain `check_delivery_progress`; store original proposed timestamp |
| Address Yes/Update | `wa_senders.confirm_delivery_address_wa` | Inline callbacks then authenticated address flow; verify consumer registration |
| Scheduled availability and template quick replies | `wa_senders.enquire_shift_availability`, `enquire_admin_availability`; `agent_app_handlers`; `delivery_hooks` availability endpoints | Local message + inline replies; fan out to linked reachable chats |
| OwnTracks start/stop URL buttons | `rider_agent` tracking tools; `create_start_job_config`, `create_stop_job_config` | URL button; check actual scheme on clients; use HTTPS landing page if custom scheme unsupported |
| Payment/reservation URL templates | `wa_senders.send_request_payment_link`, `send_reservation_link` | Text + full URL; template variable may be a suffix, so reconstruct from verified configuration |
| Static pickup/dropoff pins | `rider_agent` `send_location` calls | `send_location` / `send_venue` |
| Native current-location request | `rider_agent.request_rider_current_location`; `ordelo/wa_location.py`; `watomation/on_wa_location_handler.py`; `ordelo_datamodels/wa_location_pymodels.py` | Reply keyboard, `F.location`, pending authorized request, actor/time correlation; retain graph history |
| Customer contact card | `rider_agent.send_customer_contact` | `send_contact` requires actual phone/first name; Telegram identity does not imply phone; preserve no-phone web behavior |
| List/section options | `utils_common/wa_utils.py`, `send_button_options`, `send_section_options` | Inline rows/pagination; no PyWa `SectionList`; token/index for long LLM option text |
| Images | `watomation/routers/ai_rnd.py`; `utils_common/wa_utils.py`; `config/waba_setting.py` helpers | `send_photo`; check callers/registration before declaring active |
| Documents and catalog demos | `notebooks/wa_adhoc_run.py`, `notebooks/wa_adhoc_scripts/` | `send_document`; notebooks are not production usage evidence |
| Product sections/catalog link | `wa_senders.send_catalog`, `send_product_sections` | Storefront/Mini App or photo/text cards + SKU actions; own cart/modifier/price state |
| Replies to earlier receipt/message | `wa_senders` admin receipts; native location handler | `ReplyParameters`; store `(bot, chat_id, message_id)` per destination; WA IDs cannot be reused |
| Address/postcode WA Flows | `wa_senders.send_postcode_search_flow`; `watomation/on_flow_request_wa_handler.py`, `on_flow_request_postcode_search.py`; `/flow` | FSM conversation or Mini App; no execution of WA Flow JSON |
| Indirect customer progress | `utils_common/notify/customer_notifier.py`; `agent_app_handlers`; delivery/takeaway/location hooks | Trace publisher → subscription/outbox → adapter → external restaurant receiver; direct Telegram sends do not migrate external receiver |

Also inspect `utils_common/live_location/app_live_location_tracker.py`, prompts, formatters, login/admin links, tests and `config/params.py` for phone/WA assumptions.

## Named templates found in source

| Exact name | Observed parameters | Replacement |
| --- | --- | --- |
| `request_payment` | Name, order ID, URL variable | Local payment prompt + full checkout link |
| `send_reservation_link` | Name, reservation ID, URL variable | Local reservation text + resolved link |
| `payment_reciept_elai` | Four receipt body parameters | Local receipt renderer |
| `shift_availability` | Rider name, Yes/No quick replies | Localized shift question + inline Yes/No |
| `alert_order_notification_resolve` | Greeting, admin quick reply | Availability prompt + confirmation callback |

Call sites do not contain all approved template bodies or URL prefixes. Retrieve actual content/configuration for wording parity; do not invent it from names. `TemplateLanguage.ENGLISH_UK` becomes application localization. Scheduled messages still require onboarding, permissions and rate controls.

## Callback discriminators and domain behavior

Current `CallbackButtonData` is Pydantic with extra JSON fields; aiogram `CallbackData` is a separate packing/filter mechanism. `model_dump_json()` is not a drop-in Telegram payload.

| Existing discriminator | Retained semantics |
| --- | --- |
| `/dispatchResponse` (`command`, not `action`) | Actual rider; dispatch/order validation; only assigned rider declining same inflight dispatch reaches pre-pickup cancellation |
| `/riderLocationRequest` | Pickup/dropoff/contact distinction; reload dispatch, reject completed/unauthorized job |
| `/shiftAvailability` | Yes/No shift changes; inflight job blocks ending shift |
| `/adminAvailability` | Actual authorized admin; reply is not proof of persisted availability |
| `/RestaurantOrder-Accept`, `/RestaurantOrder-Decline` | Restaurant authorization, delivery/takeaway branching, duplicate/status checks |
| `/PickupTime` | Stale/repeated selection cannot overwrite already-set pickup time |
| `/AdminCollectionReady` | Progress gate before graph invocation |
| `/AdminAdjustPickupTime10`, `/AdminAdjustPickupTime20` | Original displayed proposal, not cumulative increments; retained trigger/rider notification |
| `/AdminTakeawayReady` | Authorized collection-ready event with channel routing |
| `/ConfirmDeliveryAddress` | Sender exists; establish intended Telegram receiver explicitly |

## Inbound routing and source gaps

`watomation/fapp_ordelo_agent.py` registers login/sysadmin, `/reset`, `/test`, `/cleardis`, `/flow`, `/live`, `/shift`, location, generic rider text, callbacks, Flow completion and two Flow request endpoints. Route commands/forms/location before generic graph text. Use `Command`/`CommandStart`, `F.text`, `F.location`, `F.contact`, `F.web_app_data` and typed callbacks as applicable. Command-menu visibility does not authorize reset/test/admin operations.

Registered Flow handlers contain hard-coded example identities/text and a completion logger. Catalog helpers refer to `waba_cat_settings` with its import commented out. Treat these as incomplete/example paths until caller tracing proves otherwise; do not perpetuate demo data. The sender's existence alone does not establish a working production flow.

No first-class WA status handler was found in the inspected registration block. Current `docs/alerts-and-notifications.md`, `GLOSSARY.md`, `docs/web-ordering-playground.md` and `docs/test-orders.md` document customer event ownership, transport evidence and domain rules. Restaurant HTTP success is not user delivery/read. Reinspect current notifier adapters/subscriptions; old feature-flag notes can be stale. W-ids are web identities, not phone/chat addresses. Exact `TEST3100` payment selection and eligible overwatch dispatching remain independent of transport.

## Refresh inventory without application imports

```bash
rg -n 'send_(message|text|template|image|document|location|contact|products|catalog)|ButtonUrl|FlowButton|SectionList|QuickReplyButton|URLButton|callback_data' ordelo watomation utils_common config --glob '*.py'
rg -n 'add_handlers|MessageHandler|CallbackButtonHandler|FlowCompletionHandler|FlowRequestHandler|IS_|filters\.' watomation --glob '*.py'
rg -n 'whatsapp|wa_id|wa_client|recipient|restaurant_msg_id|origin_channel|whatsapp_restaurant' ordelo utils_common watomation ordelo_datamodels docs --glob '*.py' --glob '*.sql' --glob '*.md'
```

Separate active registrations/reachable callers from comments, notebooks, prototypes and import-side-effect modules. Sibling customer-facing applications require their own source inspection and task scope.
