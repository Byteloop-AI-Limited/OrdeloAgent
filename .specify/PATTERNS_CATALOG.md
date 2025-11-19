# OrdeloAgent Patterns Catalog

**Quick index of all documented patterns with file locations**

---

## 🗄️ Database Patterns

### 1. Database-Triggered Webhook
**When:** Need to call FastAPI endpoint when database event occurs  
**Files:** `*.sql` (trigger function), `routers/*_hooks.py` (endpoint)  
**Example:** `restaurant_confirmation_whook()` → `/restaurant-confirmation-request`  
**Guide:** [AI_PATTERNS_GUIDE.md#database-triggered-webhook-pattern](AI_PATTERNS_GUIDE.md#database-triggered-webhook-pattern)

### 2. CTE-Based Processing
**When:** Multi-step data transformations in single function  
**Files:** `jobs_n_functions/*.sql`  
**Example:** `process_delivery()`, `job_restaurant_confirmation_timeout()`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-cte-based-data-processing](AI_PATTERNS_GUIDE.md#pattern-1-cte-based-data-processing)

### 3. Configuration Lookup with Fallback
**When:** Need entity-specific config with global default  
**Files:** Any SQL function  
**Example:** `{rest_ref}_TIMEOUT` → `DEFAULT_TIMEOUT` → hardcoded  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-2-configuration-lookup-with-fallback](AI_PATTERNS_GUIDE.md#pattern-2-configuration-lookup-with-fallback)

### 4. Idempotent Functions
**When:** Prevent duplicate processing of same event  
**Files:** `jobs_n_functions/*.sql`  
**Example:** `handle_restaurant_confirmation()` checks status first  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-conditional-function-execution](AI_PATTERNS_GUIDE.md#pattern-3-conditional-function-execution)

### 5. Row-Level Triggers
**When:** Process each inserted/updated row individually  
**Files:** `*.sql`  
**Example:** `trigger_restaurant_confirmation_request`  
**Guide:** [AI_PATTERNS_GUIDE.md#step-2-create-trigger-sql](AI_PATTERNS_GUIDE.md#step-2-create-trigger-sql)

### 6. Statement-Level Triggers
**When:** Process batch inserts as single operation  
**Files:** `dispatch.sql`, `inflight.sql`  
**Example:** `trigger_delivery_dispatch_whook` with `new_rows`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-4-bulk-processing-with-statement-level-triggers](AI_PATTERNS_GUIDE.md#pattern-4-bulk-processing-with-statement-level-triggers)

### 7. Scheduled Jobs
**When:** Periodic background processing (timeouts, cleanup, etc.)  
**Files:** `jobs_n_functions/job_*.sql`  
**Example:** `job_restaurant_confirmation_timeout()` runs every minute  
**Guide:** [AI_PATTERNS_GUIDE.md#scheduled-jobs-pattern](AI_PATTERNS_GUIDE.md#scheduled-jobs-pattern)

---

## 📱 WhatsApp Patterns

### 8. Callback Buttons
**When:** User needs to select from options  
**Files:** `routers/*_hooks.py` (send), `on_callback_wa_handler.py` (handle)  
**Example:** Restaurant selects 5/15/25 minutes  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-callback-buttons](AI_PATTERNS_GUIDE.md#pattern-1-callback-buttons)

### 9. Callback Handler Registration
**When:** Register handler for callback command  
**Files:** `on_callback_wa_handler.py`, `fapp_ordelo_agent.py`  
**Example:** `IS_RESTAURANT_CONFIRMATION` filter → `handle_restaurant_confirmation`  
**Guide:** [AI_PATTERNS_GUIDE.md#step-3-register-callback-handler](AI_PATTERNS_GUIDE.md#step-3-register-callback-handler)

### 10. Direct Messages
**When:** Simple text-based interactions  
**Files:** `on_message_wa_handler.py`  
**Example:** `/test`, `/reset`, `/live` commands  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-2-direct-messages](AI_PATTERNS_GUIDE.md#pattern-2-direct-messages)

### 11. WhatsApp Flows
**When:** Multi-step forms (address, postcode search)  
**Files:** `on_flow_request_*.py`  
**Example:** Customer address capture flow  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-whatsapp-flows](AI_PATTERNS_GUIDE.md#pattern-3-whatsapp-flows)

---

## 🌐 FastAPI Patterns

### 12. Webhook Endpoint Structure
**When:** Receive webhook from database trigger  
**Files:** `routers/*_hooks.py`  
**Example:** All `/delivery-hooks/*` endpoints  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure](AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure)

### 13. Router Organization
**When:** Group related endpoints  
**Files:** `routers/*_hooks.py`  
**Example:** `delivery_hooks.py`, `location_hooks.py`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-2-router-organization](AI_PATTERNS_GUIDE.md#pattern-2-router-organization)

### 14. Restaurant-Specific Webhooks
**When:** Call external restaurant system  
**Files:** Any router  
**Example:** `get_webhook_url(rest_ref, "rider-inflight")`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-restaurant-specific-webhooks](AI_PATTERNS_GUIDE.md#pattern-3-restaurant-specific-webhooks)

---

## 📊 Data Model Patterns

### 15. Pydantic Model Extension
**When:** Add fields to existing model  
**Files:** `ordelo_datamodels/*_pymodels.py`  
**Example:** Added `rest_confirmed_at: Optional[datetime] = None`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-pydantic-models](AI_PATTERNS_GUIDE.md#pattern-1-pydantic-models)

### 16. Status Enums
**When:** Define allowed status values  
**Files:** `*.sql` (CHECK constraint)  
**Example:** `status IN ('restaurant_unconfirmed', 'unassigned', ...)`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-2-status-enums-in-sql](AI_PATTERNS_GUIDE.md#pattern-2-status-enums-in-sql)

### 17. Nullable vs Non-Nullable
**When:** Decide field requirements  
**Files:** `*.sql`, `*_pymodels.py`  
**Example:** New fields nullable, core fields NOT NULL  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-nullable-vs-non-nullable-fields](AI_PATTERNS_GUIDE.md#pattern-3-nullable-vs-non-nullable-fields)

---

## ⚙️ Configuration Patterns

### 18. ordelo_config Table
**When:** Store any configurable value  
**Files:** `ordelo_config.sql`  
**Example:** `RESTAURANT_CONFIRMATION_TIMEOUT` = '5'  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-ordelo_config-table-structure](AI_PATTERNS_GUIDE.md#pattern-1-ordelo_config-table-structure)

### 19. Entity-Specific Config
**When:** Override global config per entity  
**Files:** Any SQL function or Python code  
**Example:** `WREN_RESTAURANT_CONFIRMATION_TIMEOUT` overrides default  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-2-configuration-naming-conventions](AI_PATTERNS_GUIDE.md#pattern-2-configuration-naming-conventions)

### 20. Config Lookup in SQL
**When:** Read config in database function  
**Files:** `jobs_n_functions/*.sql`  
**Example:** `SELECT config_value FROM ordelo_config WHERE config_key = 'KEY'`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-config-lookup-in-sql](AI_PATTERNS_GUIDE.md#pattern-3-config-lookup-in-sql)

### 21. Config Lookup in Python
**When:** Read config in FastAPI/Python  
**Files:** Any Python file  
**Example:** `client.table("ordelo_config").select(...).eq("config_key", ...)`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-4-config-lookup-in-python](AI_PATTERNS_GUIDE.md#pattern-4-config-lookup-in-python)

---

## 📝 Documentation Patterns

### 22. Module Docstrings
**When:** Every Python module  
**Files:** All `.py` files  
**Example:** See any file in `watomation/` or `ordelo/`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-module-docstring-format](AI_PATTERNS_GUIDE.md#pattern-module-docstring-format)

### 23. SQL Function Documentation
**When:** Every SQL function  
**Files:** All `.sql` files  
**Example:** See `process_delivery.sql` header  
**Guide:** [AI_PATTERNS_GUIDE.md#sql-function-documentation](AI_PATTERNS_GUIDE.md#sql-function-documentation)

### 24. Implementation Progress Tracking
**When:** Implementing any feature  
**Files:** `.specify/design/*_implementation_progress.md`  
**Example:** `restaurant_confirmation_implementation_progress.md`  
**Guide:** [AI_PATTERNS_GUIDE.md#phase-7-documentation](AI_PATTERNS_GUIDE.md#phase-7-documentation)

---

## 🔧 Integration Patterns

### 25. Supabase RPC Calls
**When:** Call database function from Python  
**Files:** Any Python file  
**Example:** `client_ordelo.rpc("handle_restaurant_confirmation", {...})`  
**Guide:** [QUICK_PATTERNS_REFERENCE.md#supabase-rpc-call](QUICK_PATTERNS_REFERENCE.md#supabase-rpc-call)

### 26. HTTP POST from SQL
**When:** Call webhook from database  
**Files:** Any webhook function  
**Example:** `http_post(webhook_url, payload::text, 'application/json')`  
**Guide:** [AI_PATTERNS_GUIDE.md#step-1-create-webhook-function-sql](AI_PATTERNS_GUIDE.md#step-1-create-webhook-function-sql)

### 27. Async Background Tasks
**When:** Non-blocking operations in FastAPI  
**Files:** `routers/*_hooks.py`  
**Example:** `background_tasks.add_task(send_notification, data)`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure](AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure)

---

## 🎯 Workflow Patterns

### 28. Status-Based State Machine
**When:** Entity progresses through states  
**Files:** Any table with status column  
**Example:** `restaurant_unconfirmed` → `unassigned` → `assigned` → `completed`  
**Guide:** [design/restaurant_confirmation_proposal.md](design/restaurant_confirmation_proposal.md)

### 29. Timeout with Default Action
**When:** User action required with fallback  
**Files:** `jobs_n_functions/job_*.sql`  
**Example:** 5-minute timeout → default to 25 minutes  
**Guide:** [design/restaurant_confirmation_patterns_used.md#pattern-7](design/restaurant_confirmation_patterns_used.md#pattern-7)

### 30. Function Chaining
**When:** One function calls another  
**Files:** Any SQL function  
**Example:** `handle_restaurant_confirmation()` calls `process_delivery()`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-3-conditional-function-execution](AI_PATTERNS_GUIDE.md#pattern-3-conditional-function-execution)

---

## 🛡️ Error Handling Patterns

### 31. Try/Except in Python
**When:** Any external call or risky operation  
**Files:** All Python files  
**Example:** All webhook endpoints and callback handlers  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure](AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure)

### 32. State Validation in SQL
**When:** Prevent invalid state transitions  
**Files:** Any UPDATE function  
**Example:** `WHERE status = 'expected_status'` in UPDATE  
**Guide:** [design/restaurant_confirmation_patterns_used.md#pattern-5](design/restaurant_confirmation_patterns_used.md#pattern-5)

### 33. RAISE NOTICE Logging
**When:** Log from SQL functions  
**Files:** Any SQL function  
**Example:** `RAISE NOTICE 'Response from HTTP POST: %', response;`  
**Guide:** [AI_PATTERNS_GUIDE.md#step-1-create-webhook-function-sql](AI_PATTERNS_GUIDE.md#step-1-create-webhook-function-sql)

### 34. Python Logger Usage
**When:** Log from Python code  
**Files:** All Python files  
**Example:** `logger.info(...)`, `logger.error(...)`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure](AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure)

---

## 📈 Performance Patterns

### 35. Early Exit in Jobs
**When:** Scheduled job with no work  
**Files:** `jobs_n_functions/job_*.sql`  
**Example:** CTE returns empty → no UPDATE executed  
**Guide:** [design/restaurant_confirmation_patterns_used.md#pattern-7](design/restaurant_confirmation_patterns_used.md#pattern-7)

### 36. Batch Processing
**When:** Process multiple records efficiently  
**Files:** Statement-level triggers  
**Example:** `trigger_delivery_dispatch_whook` processes all new rows once  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-4-bulk-processing](AI_PATTERNS_GUIDE.md#pattern-4-bulk-processing)

### 37. Async/Await
**When:** I/O operations in Python  
**Files:** All async functions  
**Example:** `await _async_wa_client.send_message(...)`  
**Guide:** [AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure](AI_PATTERNS_GUIDE.md#pattern-1-webhook-endpoint-structure)

---

## Pattern Usage Matrix

| Feature Type | Recommended Patterns |
|--------------|---------------------|
| User Confirmation | #1, #8, #9, #18, #28, #29 |
| Scheduled Processing | #7, #2, #3, #35 |
| External Webhook | #1, #12, #26, #31 |
| WhatsApp Interaction | #8, #9, #10, #37 |
| Data Model Change | #15, #16, #17 |
| Configuration | #3, #18, #19, #20, #21 |
| State Transition | #4, #28, #32 |

---

## Pattern Combinations

### Common Combinations

**User Action with Timeout:**
- Patterns: #1, #7, #8, #9, #18, #28, #29
- Example: Restaurant confirmation

**Database Event → External Notification:**
- Patterns: #1, #5, #12, #26, #31
- Example: Delivery dispatch notification

**Scheduled Cleanup/Processing:**
- Patterns: #2, #7, #3, #35
- Example: Timeout jobs, location processing

**Multi-Step Workflow:**
- Patterns: #2, #28, #30, #32
- Example: Delivery processing pipeline

---

## Anti-Patterns (Avoid These)

❌ **Hardcoded URLs** - Use ordelo_config  
❌ **No error handling** - Always try/except  
❌ **Missing logging** - Log entry/success/error  
❌ **No idempotency** - Check state before update  
❌ **Blocking calls** - Use async/await  
❌ **No configuration fallback** - Entity → Global → Default  
❌ **Skipping docstrings** - Always update  
❌ **No RETURNING clause** - Use for action logs  

---

## Quick Pattern Lookup

**Need to...**
- Trigger webhook from DB? → Pattern #1
- Send WhatsApp buttons? → Pattern #8
- Handle button click? → Pattern #9
- Schedule periodic job? → Pattern #7
- Add config value? → Pattern #18
- Extend data model? → Pattern #15
- Process in batches? → Pattern #36
- Handle timeout? → Pattern #29
- Call DB from Python? → Pattern #25
- Update module docs? → Pattern #22

---

**See Full Details:** [AI_PATTERNS_GUIDE.md](AI_PATTERNS_GUIDE.md)  
**Quick Reference:** [QUICK_PATTERNS_REFERENCE.md](QUICK_PATTERNS_REFERENCE.md)  
**Real Example:** [restaurant_confirmation_patterns_used.md](design/restaurant_confirmation_patterns_used.md)
