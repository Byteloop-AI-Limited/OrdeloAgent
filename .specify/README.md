# OrdeloAgent Documentation Index

**Welcome!** This directory contains comprehensive documentation for AI agents and developers working on OrdeloAgent.

---

## 📚 For AI Agents

### Start Here
1. **[AI Patterns Guide](AI_PATTERNS_GUIDE.md)** - Complete reference of all architectural patterns
2. **[Quick Patterns Reference](QUICK_PATTERNS_REFERENCE.md)** - Fast lookup card for common patterns

### Real-World Example
3. **[Restaurant Confirmation Patterns](design/restaurant_confirmation_patterns_used.md)** - See patterns in action

### Project Architecture
4. **[Constitution](memory/constitution.md)** - Core principles and standards (if exists)
5. **[Agents Overview](../agents.md)** - System architecture map (in memories)

---

## 🎯 Pattern Categories

### Database Patterns
- Database-triggered webhooks
- CTE-based processing
- Configuration with fallbacks
- Idempotent functions
- Scheduled jobs with pg_cron

### Integration Patterns
- WhatsApp callback buttons
- WhatsApp direct messages
- WhatsApp flows
- FastAPI webhook endpoints
- Supabase RPC calls

### Code Patterns
- Pydantic model extensions
- Module documentation standards
- Error handling
- Logging
- Async/await

---

## 📖 Implementation Guides

### Recent Features
- **[Restaurant Confirmation](design/restaurant_confirmation_summary.md)** - Complete implementation guide
- **[Restaurant Confirmation Progress](design/restaurant_confirmation_implementation_progress.md)** - Step-by-step log
- **[Restaurant Confirmation Proposal](design/restaurant_confirmation_touchpoint_proposal.md)** - Original design

### Workflows (if using /workflows)
See `.windsurf/workflows/` for executable workflows like:
- `/specify` - Create feature specifications
- `/plan` - Generate implementation plans
- `/implement` - Execute implementations
- `/analyze` - Analyze artifacts

---

## 🚀 Quick Start for New Features

### Step 1: Review Patterns
Read **[AI Patterns Guide](AI_PATTERNS_GUIDE.md)** sections relevant to your feature.

### Step 2: Check Examples
Look at **[Restaurant Confirmation Patterns](design/restaurant_confirmation_patterns_used.md)** for real implementation.

### Step 3: Use Checklist
Follow the **Complete Implementation Checklist** in the patterns guide.

### Step 4: Document
Create progress tracker and summary docs in `design/` folder.

---

## 📂 Directory Structure

```
.specify/
├── README.md (this file)
├── AI_PATTERNS_GUIDE.md (comprehensive patterns)
├── QUICK_PATTERNS_REFERENCE.md (quick lookup)
├── design/
│   ├── {feature}_proposal.md (design proposals)
│   ├── {feature}_implementation_progress.md (progress tracking)
│   ├── {feature}_summary.md (implementation summaries)
│   └── {feature}_patterns_used.md (pattern examples)
└── memory/
    └── constitution.md (project principles)
```

---

## 🔑 Key Principles

### 1. Database-First
PostgreSQL is the source of truth. Business logic lives in SQL functions.

### 2. Event-Driven
Database triggers orchestrate workflows via webhooks to FastAPI.

### 3. Configuration-Driven
All configurable values in `ordelo_config` table with entity-specific overrides.

### 4. Pattern-Based
Follow established patterns for consistency and maintainability.

### 5. Documentation-First
Update module docstrings and create progress trackers for all features.

---

## 🛠️ Common Tasks

### Add a New Webhook Endpoint
1. Create SQL trigger function
2. Create trigger
3. Create FastAPI endpoint
4. Update module docstring

**See:** [Database-Triggered Webhook Pattern](AI_PATTERNS_GUIDE.md#database-triggered-webhook-pattern)

### Add WhatsApp Callback
1. Send message with buttons
2. Create callback handler
3. Register handler in main app
4. Update module docstring

**See:** [WhatsApp Integration Patterns](AI_PATTERNS_GUIDE.md#whatsapp-integration-patterns)

### Add Scheduled Job
1. Create job function with CTEs
2. Schedule with pg_cron
3. Test with manual execution

**See:** [Scheduled Jobs Pattern](AI_PATTERNS_GUIDE.md#scheduled-jobs-pattern)

### Extend Data Model
1. Add columns to SQL table
2. Update Pydantic model with Optional fields
3. Update migration script

**See:** [Data Model Patterns](AI_PATTERNS_GUIDE.md#data-model-patterns)

---

## 📊 Code Locations

| Component | Location |
|-----------|----------|
| SQL Schema | `ordelo_datamodels/{entity}.sql` |
| SQL Functions | `ordelo_datamodels/jobs_n_functions/{name}.sql` |
| Migrations | `ordelo_datamodels/migrations/{desc}.sql` |
| Data Models | `ordelo_datamodels/{domain}_pymodels.py` |
| FastAPI Routers | `watomation/routers/{domain}_hooks.py` |
| WA Callbacks | `watomation/on_callback_wa_handler.py` |
| WA Messages | `watomation/on_message_wa_handler.py` |
| Main App | `watomation/fapp_ordelo_agent.py` |
| Config | `config/{setting}_setting.py` |

---

## 🎓 Learning Path

### For New AI Agents
1. Read [Quick Patterns Reference](QUICK_PATTERNS_REFERENCE.md) (5 min)
2. Skim [AI Patterns Guide](AI_PATTERNS_GUIDE.md) (15 min)
3. Study [Restaurant Confirmation Example](design/restaurant_confirmation_patterns_used.md) (10 min)
4. Review existing code matching your feature type (20 min)

### For Implementing Features
1. Review relevant pattern sections
2. Check similar existing implementations
3. Follow implementation checklist
4. Document as you go
5. Update this index if new patterns emerge

---

## 🔍 Finding Information

### "How do I trigger a webhook from database?"
→ [Database-Triggered Webhook Pattern](AI_PATTERNS_GUIDE.md#database-triggered-webhook-pattern)

### "How do I send WhatsApp buttons?"
→ [WhatsApp Callback Pattern](AI_PATTERNS_GUIDE.md#pattern-1-callback-buttons)

### "How do I handle configuration?"
→ [Configuration Management](AI_PATTERNS_GUIDE.md#configuration-management)

### "How do I write SQL functions?"
→ [PostgreSQL Patterns](AI_PATTERNS_GUIDE.md#postgresql-patterns)

### "What's the module docstring format?"
→ [Module Documentation Standards](AI_PATTERNS_GUIDE.md#module-documentation-standards)

### "How do I schedule jobs?"
→ [Scheduled Jobs Pattern](AI_PATTERNS_GUIDE.md#scheduled-jobs-pattern)

---

## 🤝 Contributing

When implementing new features:

1. **Follow existing patterns** - Don't reinvent the wheel
2. **Document new patterns** - If you create something new, add it to the guide
3. **Update examples** - Add your feature as an example if it's instructive
4. **Keep it current** - Update this index and guides as the project evolves

---

## 📞 Support

- **Patterns unclear?** Check the real-world example in restaurant confirmation
- **Missing pattern?** Review existing code for similar features
- **New pattern needed?** Document it and add to the guide
- **Questions?** Refer to constitution and architecture docs

---

## 🎯 Success Metrics

A well-implemented feature should:
- ✅ Follow at least 3-5 established patterns
- ✅ Have comprehensive error handling
- ✅ Include proper logging
- ✅ Update all module docstrings
- ✅ Create progress documentation
- ✅ Include rollback plan
- ✅ Have monitoring queries

---

**Last Updated:** 2025-11-18  
**Version:** 1.0.0  
**Maintained By:** AI Agents + Development Team

---

## Quick Links

- [Full Patterns Guide](AI_PATTERNS_GUIDE.md)
- [Quick Reference Card](QUICK_PATTERNS_REFERENCE.md)
- [Real Example: Restaurant Confirmation](design/restaurant_confirmation_patterns_used.md)
- [Implementation Checklist](AI_PATTERNS_GUIDE.md#complete-implementation-checklist)
