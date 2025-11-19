# OrdeloAgent Architecture Patterns Guide for AI

**Version:** 1.0.0  
**Last Updated:** 2025-11-18  
**Purpose:** Reference guide for AI agents implementing new features in OrdeloAgent

---

## Table of Contents

1. [Core Architecture Principles](#core-architecture-principles)
2. [Database-Triggered Webhook Pattern](#database-triggered-webhook-pattern)
3. [WhatsApp Integration Patterns](#whatsapp-integration-patterns)
4. [PostgreSQL Patterns](#postgresql-patterns)
5. [FastAPI Endpoint Patterns](#fastapi-endpoint-patterns)
6. [Configuration Management](#configuration-management)
7. [Data Model Patterns](#data-model-patterns)
8. [Scheduled Jobs Pattern](#scheduled-jobs-pattern)
9. [Module Documentation Standards](#module-documentation-standards)
10. [Complete Implementation Checklist](#complete-implementation-checklist)

---

## Core Architecture Principles

### 1. Database-First Design
- PostgreSQL is the source of truth
- Business logic lives in SQL functions
- Database triggers orchestrate workflows
- FastAPI endpoints are thin wrappers

### 2. Event-Driven Architecture
- Database changes trigger webhooks
- Webhooks call FastAPI endpoints
- FastAPI coordinates external services (WhatsApp, etc.)
- Async processing for non-blocking operations

### 3. Configuration-Driven Behavior
- All configurable values in `ordelo_config` table
- Support for global and entity-specific configs
- Pattern: `{entity_ref}_CONFIG_KEY` → fallback to `CONFIG_KEY`

---

## Database-Triggered Webhook Pattern

### Pattern Overview

```
Database Event → Trigger → Webhook Function → HTTP POST → FastAPI Endpoint → Business Logic
```

### Implementation Steps

#### Step 1: Create Webhook Function (SQL)

```sql
CREATE OR REPLACE FUNCTION {entity}_{event}_whook()
RETURNS TRIGGER AS $$
DECLARE
  response json;
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
BEGIN
  -- Build JSON payload from trigger data
  SELECT json_build_object(
    'key1', NEW.column1,
    'key2', NEW.column2,
    'nested', json_build_array(row_to_json(NEW))
  ) INTO webhook_payload;
  
  -- Get base URL from config with fallback
  SELECT config_value INTO ordelo_app_url 
  FROM ordelo_config 
  WHERE config_key = 'ORDELO_APP_URL';
  
  IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
    ordelo_app_url := 'https://rider-agent.ordelo.app';
  END IF;
  
  -- Construct webhook URL
  webhook_url := ordelo_app_url || '/delivery-hooks/{endpoint-name}';
  
  -- Make HTTP POST request
  response := (
    SELECT content
    FROM http_post(
      webhook_url,
      webhook_payload::text,
      'application/json'
    )
  );
  
  -- Log response
  RAISE NOTICE 'Response from HTTP POST to {endpoint}: %', response;
  
  RETURN NEW;  -- or NULL for AFTER triggers
END;
$$ LANGUAGE plpgsql;
```

#### Step 2: Create Trigger (SQL)

**Row-Level Trigger (fires per row):**
```sql
CREATE TRIGGER trigger_{entity}_{event}
AFTER INSERT ON {table_name}
FOR EACH ROW
WHEN (NEW.status = 'target_status')  -- Optional condition
EXECUTE FUNCTION {entity}_{event}_whook();
```

**Statement-Level Trigger (fires once per statement, for bulk operations):**
```sql
CREATE TRIGGER trigger_{entity}_{event}
AFTER INSERT ON {table_name}
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION {entity}_{event}_whook_statement();
```

#### Step 3: Create FastAPI Endpoint

```python
# In watomation/routers/{router_name}.py

@router.post("/{endpoint-name}")
async def {endpoint_name}_hook(
    payload: dict = Depends(get_payload),
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Webhook triggered by database event.
    
    Triggered by: {describe trigger condition}
    
    Payload structure:
    {
        "key1": "value1",
        "key2": "value2"
    }
    
    Returns:
        dict: Status of the operation
    """
    try:
        # Extract data from payload
        entity_id = payload.get("entity_id")
        
        logger.info(f"Processing {endpoint_name} for {entity_id}")
        
        # Perform business logic
        # - Database operations via client.table()
        # - External API calls
        # - WhatsApp messages
        
        return {"status": "success", "entity_id": entity_id}
        
    except Exception as e:
        logger.error(f"Error in {endpoint_name}_hook: {e}")
        return {"status": "error", "message": str(e)}
```

### Real Examples in Codebase

1. **Restaurant Confirmation Request**
   - Trigger: `trigger_restaurant_confirmation_request` on `delivery_summary` INSERT
   - Function: `restaurant_confirmation_whook()`
   - Endpoint: `/delivery-hooks/restaurant-confirmation-request`
   - Purpose: Send WhatsApp to restaurant when order created

2. **Delivery Dispatch**
   - Trigger: `trigger_delivery_dispatch_whook` on `delivery_dispatch` INSERT
   - Function: `delivery_dispatch_whook_statement()` (statement-level)
   - Endpoint: `/delivery-hooks/delivery-dispatch`
   - Purpose: Notify riders of new delivery opportunities

3. **Delivery Timeout**
   - Trigger: `trigger_delivery_summary_timedout` on `delivery_summary` UPDATE
   - Function: `delivery_summary_timedout_whook()`
   - Endpoint: `/delivery-hooks/delivery-timedout`
   - Purpose: Notify restaurant when delivery times out

---

## WhatsApp Integration Patterns

### Pattern 1: Callback Buttons

Used for user interactions requiring a choice (Accept/Decline, time selection, etc.)

#### Step 1: Send Message with Buttons (FastAPI)

```python
from pywa.types import Button
import json

# Create callback payloads
button1_payload = {
    "command": "/commandName",
    "entity_id": entity_id,
    "param1": value1
}

button2_payload = {
    "command": "/commandName",
    "entity_id": entity_id,
    "param1": value2
}

# Create buttons
buttons = [
    Button(
        title="Option 1",
        callback_data=json.dumps(button1_payload)
    ),
    Button(
        title="Option 2",
        callback_data=json.dumps(button2_payload)
    ),
]

# Send message
await _async_wa_client.send_message(
    to=recipient_phone,
    text="Message text here",
    buttons=buttons
)
```

#### Step 2: Create Callback Handler

```python
# In watomation/on_callback_wa_handler.py

async def handle_{feature}_callback(wa: WhatsApp, msg: Message):
    """
    Handles {feature} callback from WhatsApp buttons.
    
    Callback data structure:
    {
        "command": "/commandName",
        "entity_id": "123",
        "param1": "value"
    }
    """
    try:
        sender = msg.sender
        callback_data: dict = json.loads(msg.data)
        
        entity_id = callback_data.get("entity_id")
        param1 = callback_data.get("param1")
        
        logger.info(f"Callback received: entity={entity_id}, param={param1}")
        
        # Call database function via Supabase RPC
        result = client_ordelo.rpc(
            "database_function_name",
            {
                "p_entity_id": entity_id,
                "p_param1": param1
            }
        ).execute()
        
        if result.data:
            await wa.send_message(
                to=sender,
                text=f"✅ Success message"
            )
            logger.info(f"Success for {entity_id}")
        else:
            await wa.send_message(
                to=sender,
                text="⚠️ Error or already processed message"
            )
            
    except Exception as e:
        logger.error(f"Error handling callback: {e}")
        await wa.send_message(
            to=msg.sender,
            text="❌ Error processing request. Please contact support."
        )
```

#### Step 3: Register Callback Handler

```python
# In watomation/fapp_ordelo_agent.py

# Import handler
from watomation.on_callback_wa_handler import handle_{feature}_callback

# Define filter
IS_{FEATURE}_CALLBACK = filters.contains("/commandName", ignore_case=False)

# Register handler
wa.add_handlers(
    # ... other handlers ...
    handlers.CallbackButtonHandler(
        callback=handle_{feature}_callback,
        filters=IS_{FEATURE}_CALLBACK
    ),
)
```

### Pattern 2: Direct Messages

For simple text responses or commands.

```python
# In watomation/on_message_wa_handler.py

async def handle_{feature}_message(wa: WhatsApp, msg: Message):
    """Process {feature} text message."""
    recipient = msg.sender
    message_text = msg.text
    
    # Process message
    # ...
    
    await wa.send_message(
        to=recipient,
        text="Response text"
    )
```

### Pattern 3: WhatsApp Flows

For complex multi-step forms (address capture, etc.). See existing flow handlers in `on_flow_request_wa_handler.py`.

---

## PostgreSQL Patterns

### Pattern 1: CTE-Based Data Processing

Common Table Expressions (CTEs) for complex, multi-step operations.

```sql
CREATE OR REPLACE FUNCTION process_{entity}()
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH step1_data AS (
    -- First transformation/selection
    SELECT col1, col2, COUNT(*) as count
    FROM source_table
    WHERE condition
    GROUP BY col1, col2
  ),
  step2_update AS (
    -- Update based on step1
    UPDATE target_table t
    SET status = 'new_status'
    FROM step1_data s
    WHERE t.id = s.col1
    RETURNING 'Updated ' || t.id AS action
  ),
  step3_insert AS (
    -- Insert new records
    INSERT INTO another_table (col1, col2)
    SELECT col1, col2
    FROM step1_data
    WHERE count > 0
    RETURNING 'Inserted ' || col1 AS action
  )
  -- Combine results
  SELECT action FROM step2_update
  UNION ALL
  SELECT action FROM step3_insert;
END;
$$ LANGUAGE plpgsql;
```

**Key Principles:**
- Each CTE is a logical step
- CTEs can reference previous CTEs
- Use RETURNING to capture results
- UNION ALL to combine action logs

### Pattern 2: Configuration Lookup with Fallback

```sql
-- Entity-specific config with fallback to default
SELECT COALESCE(
  (SELECT config_value::INTEGER 
   FROM ordelo_config 
   WHERE config_key = '{entity_ref}_CONFIG_KEY'
   LIMIT 1),
  (SELECT config_value::INTEGER 
   FROM ordelo_config 
   WHERE config_key = 'CONFIG_KEY'
   LIMIT 1),
  default_value  -- Hardcoded fallback
) AS config_value;
```

### Pattern 3: Conditional Function Execution

```sql
CREATE OR REPLACE FUNCTION handle_{entity}(p_param VARCHAR)
RETURNS BOOLEAN AS $$
DECLARE
  v_updated BOOLEAN;
BEGIN
  -- Attempt update with condition
  UPDATE target_table
  SET status = 'new_status',
      updated_at = NOW()
  WHERE id = p_param
    AND status = 'required_status'  -- Only update if in correct state
  RETURNING TRUE INTO v_updated;
  
  IF v_updated THEN
    -- Success: trigger downstream processing
    PERFORM downstream_function();
    RETURN TRUE;
  ELSE
    -- No update: already processed or not found
    RETURN FALSE;
  END IF;
END;
$$ LANGUAGE plpgsql;
```

### Pattern 4: Bulk Processing with Statement-Level Triggers

```sql
-- Access all new rows via REFERENCING clause
CREATE OR REPLACE FUNCTION process_bulk_insert()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
BEGIN
  -- Aggregate all new rows into single payload
  SELECT json_build_object(
    'bulk_data', json_agg(row_to_json(t))
  )
  INTO webhook_payload
  FROM (
    SELECT nr.*, other.data
    FROM new_rows nr  -- Special table containing all inserted rows
    JOIN other_table other ON nr.id = other.id
  ) t;
  
  -- Single HTTP call for all rows
  -- ... http_post logic ...
  
  RETURN NULL;  -- Statement-level triggers return NULL
END;
$$ LANGUAGE plpgsql;
```

---

## FastAPI Endpoint Patterns

### Pattern 1: Webhook Endpoint Structure

```python
# Standard webhook endpoint structure

@router.post("/{endpoint-name}")
async def {endpoint_name}_hook(
    payload: dict = Depends(get_payload),
    background_tasks: BackgroundTasks = None,  # Optional for async work
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """
    Brief description of webhook purpose.
    
    Triggered by: Database trigger description
    
    Payload structure:
    {
        "field1": "description",
        "field2": "description"
    }
    
    Returns:
        dict: Status response
    """
    try:
        # 1. Extract and validate payload
        required_field = payload.get("required_field")
        if not required_field:
            logger.error("Missing required_field in payload")
            return {"status": "error", "message": "Missing required field"}
        
        # 2. Log entry
        logger.info(f"Processing {endpoint_name} for {required_field}")
        
        # 3. Database operations (if needed)
        data = client.table("table_name")\
            .select("*")\
            .eq("id", required_field)\
            .execute()
        
        # 4. Business logic
        # - Process data
        # - Make decisions
        # - Prepare messages
        
        # 5. External service calls (WhatsApp, etc.)
        if background_tasks:
            background_tasks.add_task(send_notification, data)
        else:
            await send_notification(data)
        
        # 6. Return success
        logger.info(f"Successfully processed {required_field}")
        return {"status": "success", "processed": required_field}
        
    except Exception as e:
        # 7. Error handling
        logger.error(f"Error in {endpoint_name}_hook: {e}")
        return {"status": "error", "message": str(e)}
```

### Pattern 2: Router Organization

```python
# In watomation/routers/{domain}_hooks.py

from fastapi import APIRouter, Request, Depends
from config import logger, _async_wa_client, pg_settings
from pywa_async import WhatsApp

# Helper function
async def get_payload(request: Request):
    return await request.json()

# Client instances
client = pg_settings.client

# Router definition
router = APIRouter(tags=["{domain}_hooks"])

# Endpoints follow...
```

### Pattern 3: Restaurant-Specific Webhooks

For webhooks that need to call restaurant-specific external endpoints:

```python
from config import get_webhook_url

# Extract restaurant reference from order number
rest_ref = order_number.split("-")[0]  # e.g., "WREN-12345" → "WREN"

# Get restaurant-specific webhook URL
webhook_url = get_webhook_url(rest_ref, "event-type")

# Make HTTP call to restaurant system
async with httpx.AsyncClient() as client:
    response = await client.post(
        webhook_url,
        json=payload
    )
```

---

## Configuration Management

### Pattern 1: ordelo_config Table Structure

```sql
-- All configuration stored in key-value table
CREATE TABLE ordelo_config (
    config_key     VARCHAR(100) PRIMARY KEY,
    config_value   TEXT NOT NULL,
    description    TEXT,
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### Pattern 2: Configuration Naming Conventions

**Global Config:**
```
CONFIG_KEY_NAME
```
Examples:
- `ORDELO_APP_URL`
- `RESTAURANT_CONFIRMATION_TIMEOUT`
- `DELIVERY_TIMEOUT_TIME`
- `CONFIRMATION_CODE_SALT`

**Entity-Specific Config:**
```
{ENTITY_REF}_CONFIG_KEY_NAME
```
Examples:
- `WREN_RESTAURANT_CONFIRMATION_TIMEOUT`
- `WREN_APP_URL`
- `DISPATCH_BATCH_SIZE_BICYCLE`
- `DISPATCH_BATCH_SIZE_MOTORBIKE`

### Pattern 3: Config Lookup in SQL

```sql
-- Simple lookup
SELECT config_value 
FROM ordelo_config 
WHERE config_key = 'KEY_NAME'
LIMIT 1;

-- With fallback
SELECT COALESCE(
  (SELECT config_value FROM ordelo_config WHERE config_key = 'ENTITY_KEY' LIMIT 1),
  (SELECT config_value FROM ordelo_config WHERE config_key = 'DEFAULT_KEY' LIMIT 1),
  'hardcoded_default'
) AS value;

-- Type casting
SELECT config_value::INTEGER FROM ordelo_config WHERE config_key = 'NUMERIC_KEY';
SELECT config_value::BOOLEAN FROM ordelo_config WHERE config_key = 'BOOL_KEY';
```

### Pattern 4: Config Lookup in Python

```python
# Via Supabase client
config = client.table("ordelo_config")\
    .select("config_value")\
    .eq("config_key", "KEY_NAME")\
    .single()\
    .execute()

value = config.data["config_value"]

# Via config/params.py for restaurant-specific URLs
from config import get_webhook_url

url = get_webhook_url(rest_ref="WREN", type="rider-inflight")
```

---

## Data Model Patterns

### Pattern 1: Pydantic Models

```python
# In ordelo_datamodels/{domain}_pymodels.py

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime, date

class EntityModel(BaseModel):
    # Required fields
    id: str = Field(..., max_length=100)
    name: str
    status: str = Field(..., max_length=50)
    
    # Optional fields (use Optional and default=None)
    confirmed_at: Optional[datetime] = None
    metadata: Optional[dict] = None
    
    # Numeric fields with defaults
    count: int = 0
    amount: float = 0.0
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    # Computed properties
    @property
    def display_name(self) -> str:
        """Generate display-friendly name."""
        return f"{self.name} ({self.id})"
```

### Pattern 2: Status Enums in SQL

```sql
-- Use CHECK constraints for status fields
ALTER TABLE table_name
  ADD CONSTRAINT table_name_status_check
    CHECK (status IN (
      'status_1',
      'status_2',
      'status_3'
    ));

-- Update constraint when adding new statuses
ALTER TABLE table_name
  DROP CONSTRAINT table_name_status_check,
  ADD CONSTRAINT table_name_status_check
    CHECK (status IN (
      'new_status',
      'status_1',
      'status_2',
      'status_3'
    ));
```

### Pattern 3: Nullable vs Non-Nullable Fields

**SQL:**
```sql
-- Non-nullable: Required from the start
column_name TYPE NOT NULL

-- Nullable: Added later or optional
column_name TYPE

-- Nullable with default
column_name TYPE DEFAULT 'default_value'
```

**Pydantic:**
```python
# Required field
field: str

# Optional field
field: Optional[str] = None

# With default value
field: str = "default"
```

---

## Scheduled Jobs Pattern

### Pattern 1: pg_cron Job Function

```sql
CREATE OR REPLACE FUNCTION job_{job_name}(p_optional_param VARCHAR DEFAULT NULL)
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (
    -- Find records that need processing
    SELECT id, data
    FROM table_name
    WHERE status = 'pending'
      AND (p_optional_param IS NULL OR entity_ref = p_optional_param)
  ),
  processed AS (
    -- Process the records
    UPDATE table_name t
    SET status = 'processed',
        processed_at = NOW()
    FROM candidates c
    WHERE t.id = c.id
    RETURNING 'Processed ' || t.id AS action
  )
  SELECT action FROM processed;
END;
$$ LANGUAGE plpgsql;
```

### Pattern 2: Schedule Job

```sql
-- Schedule to run every minute
SELECT cron.schedule(
  'job_name',
  '* * * * *',
  $$SELECT * FROM job_{job_name}()$$
);

-- Schedule to run every 5 seconds (requires custom setup)
SELECT cron.schedule(
  'job_name',
  '*/5 * * * * *',
  $$SELECT * FROM job_{job_name}()$$
);

-- Schedule with parameter
SELECT cron.schedule(
  'job_name_entity',
  '* * * * *',
  $$SELECT * FROM job_{job_name}('ENTITY_REF')$$
);
```

### Pattern 3: Job with Early Exit

```sql
CREATE OR REPLACE FUNCTION job_{job_name}()
RETURNS TABLE(action TEXT) AS $$
DECLARE
  has_pending BOOLEAN;
BEGIN
  -- Check if there's work to do
  SELECT EXISTS (
    SELECT 1 FROM table_name WHERE status = 'pending' LIMIT 1
  ) INTO has_pending;
  
  IF NOT has_pending THEN
    -- Early exit if no work
    RETURN QUERY SELECT 'No pending records found.'::text AS action;
    RETURN;
  END IF;
  
  -- Process records
  RETURN QUERY
  WITH ... -- CTEs for processing
  SELECT action FROM ...;
END;
$$ LANGUAGE plpgsql;
```

---

## Module Documentation Standards

### Pattern: Module Docstring Format

```python
"""
Brief one-line description of module purpose
    . First key responsibility or feature
    . Second key responsibility or feature
    . Third key responsibility or feature
    . Additional features listed with bullets
    . Keep descriptions concise and action-oriented
  Functions/Classes:
    . function_name_1 - Brief description
    . function_name_2 - Brief description
    . ClassName - Brief description
"""
```

**Example:**
```python
"""
WhatsApp callback button handler for delivery dispatch responses
    . Processes rider responses to delivery dispatch assignments
    . Validates callback data and updates delivery status
    . Integrates with OrdeloAgent delivery graph logic
    . Handles cases where jobs are no longer available
    . Provides feedback to riders about dispatch status
  Functions/Classes:
    . dispatch_response - Processes rider responses to delivery dispatch
    . rider_request_location - Handles rider location requests
    . handle_restaurant_confirmation - Processes restaurant prep time confirmation
"""
```

### SQL Function Documentation

```sql
/**
Function Name and Purpose

Where This Fits in the Journey:
    - Context in overall workflow
    - Step number if part of sequence
    - Relationship to other functions

Invocation:
    - How and when this function is called
    - Trigger conditions or scheduled job details

Purpose:
    - What this function does
    - Key responsibilities
    - Expected outcomes

Dependencies:
    - Reads from: table1, table2, config_keys
    - Writes to: table3, table4
    - Calls: other_function1(), other_function2()

Side Effects:
    1. Database changes
    2. External API calls
    3. Triggered workflows

Parameters:
    - p_param1: Description and type
    - p_param2: Description and type

Returns:
    - Return type and description

See also: Related documentation files
**/
```

---

## Complete Implementation Checklist

Use this checklist when implementing a new feature:

### Phase 1: Design & Planning
- [ ] Review existing patterns in this guide
- [ ] Identify which patterns apply to your feature
- [ ] Design database schema changes (if needed)
- [ ] Design workflow and state transitions
- [ ] Identify configuration needs
- [ ] Document design decisions

### Phase 2: Database Layer
- [ ] Create/update table schema with proper constraints
- [ ] Add configuration entries to `ordelo_config`
- [ ] Create database functions with CTE patterns
- [ ] Create webhook trigger functions
- [ ] Create triggers (row-level or statement-level)
- [ ] Create scheduled job functions (if needed)
- [ ] Add comprehensive SQL comments/documentation

### Phase 3: Data Models
- [ ] Update Pydantic models in `ordelo_datamodels/`
- [ ] Add new optional fields with `Optional[Type] = None`
- [ ] Add computed properties if needed
- [ ] Test model serialization/deserialization

### Phase 4: FastAPI Endpoints
- [ ] Create webhook endpoint in appropriate router
- [ ] Follow standard endpoint structure
- [ ] Add proper error handling
- [ ] Add logging at key points
- [ ] Update router module docstring

### Phase 5: WhatsApp Integration (if needed)
- [ ] Create callback handler function
- [ ] Register handler in `fapp_ordelo_agent.py`
- [ ] Define filter for callback command
- [ ] Add to `wa.add_handlers()`
- [ ] Update module docstring

### Phase 6: Testing
- [ ] Test database functions independently
- [ ] Test trigger firing conditions
- [ ] Test webhook endpoint with sample payloads
- [ ] Test WhatsApp callback flow end-to-end
- [ ] Test timeout/error scenarios
- [ ] Test configuration fallback logic

### Phase 7: Documentation
- [ ] Update module docstrings
- [ ] Create implementation progress tracker
- [ ] Document configuration requirements
- [ ] Add monitoring queries
- [ ] Create rollback plan
- [ ] Update this patterns guide if new patterns emerged

---

## Quick Reference: File Locations

### SQL Files
- **Schema:** `ordelo_datamodels/{entity}.sql`
- **Functions:** `ordelo_datamodels/jobs_n_functions/{function_name}.sql`
- **Migrations:** `ordelo_datamodels/migrations/{description}.sql`

### Python Files
- **Data Models:** `ordelo_datamodels/{domain}_pymodels.py`
- **FastAPI Routers:** `watomation/routers/{domain}_hooks.py`
- **WA Callbacks:** `watomation/on_callback_wa_handler.py`
- **WA Messages:** `watomation/on_message_wa_handler.py`
- **Main App:** `watomation/fapp_ordelo_agent.py`
- **Config:** `config/{setting_name}_setting.py`

### Documentation
- **Design Proposals:** `.specify/design/{feature}_proposal.md`
- **Progress Tracking:** `.specify/design/{feature}_implementation_progress.md`
- **Summaries:** `.specify/design/{feature}_summary.md`

---

## Common Pitfalls to Avoid

1. **Don't hardcode URLs** - Always use `ordelo_config` table
2. **Don't skip error handling** - Wrap webhook calls in try/except
3. **Don't forget logging** - Log at entry, success, and error points
4. **Don't ignore idempotency** - Check state before updating
5. **Don't create orphan triggers** - Always document trigger-function pairs
6. **Don't skip module docstrings** - Update when adding functions
7. **Don't use blocking calls** - Use async/await for I/O operations
8. **Don't forget configuration fallbacks** - Entity-specific → Global → Hardcoded
9. **Don't skip RETURNING clauses** - Use for action logging in CTEs
10. **Don't forget NULL handling** - Use COALESCE and Optional types

---

## Pattern Evolution

This guide will evolve as new patterns emerge. When implementing features:

1. **Follow existing patterns** when they fit
2. **Document new patterns** when you create them
3. **Update this guide** when patterns change
4. **Question patterns** that seem inefficient

---

**End of Guide**

For questions or clarifications, refer to:
- Constitution: `.specify/memory/constitution.md`
- Architecture Map: `agents.md` in memories
- Existing implementations in codebase
