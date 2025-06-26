"""
WhatsApp automation and webhook handlers for Ordelo delivery system
    . Contains FastAPI routers for delivery, location and alert webhooks
    . Handles WhatsApp message processing and flow requests
    . Manages delivery dispatch, inflight tracking and missed dispatch notifications
    . Processes live location updates and rider tracking
    . Handles failure notifications and alert management
    . Integrates with PostgreSQL database triggers via webhook pattern
    . Uses function chaining for complex workflow operations
  Functions/Modules:
    . on_message_wa_handler - Processes incoming WhatsApp messages
    . on_flow_request_wa_handler - Handles WhatsApp flow requests
    . on_flow_request_postcode_search - Manages postcode search flows
    . on_callback_wa_handler - Processes WhatsApp callback button events
    . fapp_ordelo_agent - Main FastAPI application with WhatsApp integration
    . fapp_ordelo_agent_wo_wa - FastAPI application without WhatsApp integration
"""
