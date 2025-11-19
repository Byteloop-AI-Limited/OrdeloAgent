# Quick Patterns Reference Card

**For AI Agents:** Fast lookup of common OrdeloAgent patterns

---

## 🔄 Database → Webhook → FastAPI Flow

```
1. SQL Trigger Function → 2. HTTP POST → 3. FastAPI Endpoint → 4. Business Logic
```

**Files:**
- `ordelo_datamodels/{table}.sql` - Trigger function
- `watomation/routers/{domain}_hooks.py` - FastAPI endpoint

---

## 📱 WhatsApp Callback Flow

```
1. Send Buttons → 2. User Clicks → 3. Callback Handler → 4. DB Function → 5. Response
```

**Files:**
- `watomation/routers/{domain}_hooks.py` - Send buttons
- `watomation/on_callback_wa_handler.py` - Handle callback
- `watomation/fapp_ordelo_agent.py` - Register handler

---

## ⚙️ Configuration Lookup

```sql
-- Entity-specific with fallback
COALESCE(
  (SELECT config_value FROM ordelo_config WHERE config_key = '{ENTITY}_KEY'),
  (SELECT config_value FROM ordelo_config WHERE config_key = 'DEFAULT_KEY'),
  'fallback_value'
)
```

---

## 🗄️ CTE Pattern

```sql
WITH step1 AS (
  SELECT ... FROM ... WHERE ...
),
step2_update AS (
  UPDATE ... SET ... FROM step1 ... RETURNING ...
),
step3_insert AS (
  INSERT INTO ... SELECT ... FROM step1 ... RETURNING ...
)
SELECT * FROM step2_update
UNION ALL
SELECT * FROM step3_insert;
```

---

## 🎯 Trigger Types

**Row-Level (per row):**
```sql
CREATE TRIGGER trigger_name
AFTER INSERT ON table_name
FOR EACH ROW
WHEN (NEW.status = 'value')
EXECUTE FUNCTION function_name();
```

**Statement-Level (once per statement):**
```sql
CREATE TRIGGER trigger_name
AFTER INSERT ON table_name
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION function_name();
```

---

## 📝 Module Docstring

```python
"""
One-line description
    . Feature 1
    . Feature 2
    . Feature 3
  Functions/Classes:
    . function_name - Description
    . ClassName - Description
"""
```

---

## 🔐 Supabase RPC Call

```python
result = client_ordelo.rpc(
    "function_name",
    {
        "p_param1": value1,
        "p_param2": value2
    }
).execute()

if result.data:
    # Success
else:
    # Already processed or error
```

---

## ⏰ Scheduled Job

```sql
CREATE OR REPLACE FUNCTION job_name(p_param VARCHAR DEFAULT NULL)
RETURNS TABLE(action TEXT) AS $$
BEGIN
  RETURN QUERY
  WITH candidates AS (...),
  processed AS (...)
  SELECT action FROM processed;
END;
$$ LANGUAGE plpgsql;

-- Schedule
SELECT cron.schedule('job_name', '* * * * *', $$SELECT * FROM job_name()$$);
```

---

## 🚀 FastAPI Endpoint Template

```python
@router.post("/endpoint-name")
async def endpoint_hook(
    payload: dict = Depends(get_payload),
    _async_wa_client: WhatsApp = _async_wa_client,
):
    """Docstring with trigger info and payload structure."""
    try:
        # Extract
        entity_id = payload.get("entity_id")
        
        # Log
        logger.info(f"Processing {entity_id}")
        
        # Business logic
        # ...
        
        # Return
        return {"status": "success", "entity_id": entity_id}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"status": "error", "message": str(e)}
```

---

## 📊 Pydantic Model

```python
class ModelName(BaseModel):
    # Required
    id: str = Field(..., max_length=100)
    status: str
    
    # Optional (new fields)
    new_field: Optional[datetime] = None
    
    # Defaults
    count: int = 0
    
    # Computed
    @property
    def computed(self) -> str:
        return f"{self.id}-computed"
```

---

## 🔘 WhatsApp Buttons

```python
from pywa.types import Button
import json

buttons = [
    Button(
        title="Option 1",
        callback_data=json.dumps({
            "command": "/commandName",
            "param": value1
        })
    ),
    Button(
        title="Option 2",
        callback_data=json.dumps({
            "command": "/commandName",
            "param": value2
        })
    ),
]

await _async_wa_client.send_message(
    to=phone,
    text="Message",
    buttons=buttons
)
```

---

## 🎯 Callback Handler Registration

```python
# 1. Import
from watomation.on_callback_wa_handler import handle_feature

# 2. Define filter
IS_FEATURE = filters.contains("/commandName", ignore_case=False)

# 3. Register
wa.add_handlers(
    handlers.CallbackButtonHandler(
        callback=handle_feature,
        filters=IS_FEATURE
    ),
)
```

---

## 📂 File Locations

| Type | Location |
|------|----------|
| Schema | `ordelo_datamodels/{entity}.sql` |
| Functions | `ordelo_datamodels/jobs_n_functions/{name}.sql` |
| Migrations | `ordelo_datamodels/migrations/{desc}.sql` |
| Models | `ordelo_datamodels/{domain}_pymodels.py` |
| Routers | `watomation/routers/{domain}_hooks.py` |
| Callbacks | `watomation/on_callback_wa_handler.py` |
| Main App | `watomation/fapp_ordelo_agent.py` |

---

## ✅ Implementation Checklist

1. [ ] Design schema & workflow
2. [ ] Create SQL functions with CTEs
3. [ ] Create trigger & webhook function
4. [ ] Update Pydantic models
5. [ ] Create FastAPI endpoint
6. [ ] Create callback handler (if needed)
7. [ ] Register handler in main app
8. [ ] Update module docstrings
9. [ ] Test end-to-end
10. [ ] Document & create progress tracker

---

## 🚫 Common Mistakes

- ❌ Hardcoding URLs (use `ordelo_config`)
- ❌ Missing error handling
- ❌ Forgetting to log
- ❌ No idempotency checks
- ❌ Skipping module docstrings
- ❌ Using blocking calls (use async)
- ❌ No configuration fallbacks
- ❌ Missing RETURNING clauses

---

**See full guide:** `.specify/AI_PATTERNS_GUIDE.md`
