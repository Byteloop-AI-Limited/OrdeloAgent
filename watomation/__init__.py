"""
WhatsApp automation and webhook handlers for Ordelo delivery system
    . Contains FastAPI routers for delivery, location and alert webhooks
    . Handles WhatsApp message processing and flow requests
    . Manages delivery dispatch, inflight tracking and missed dispatch notifications
    . Processes live location updates and rider tracking
    . Handles failure notifications and alert management

Functions/Modules:
    . on_message_wa_handler - Processes incoming WhatsApp messages
    . on_flow_request_wa_handler - Handles WhatsApp flow requests
    . routers/delivery_hooks.py - Delivery dispatch and tracking webhooks
    . routers/location_hooks.py - Live location and rider tracking webhooks
    . routers/alert_hooks.py - Failure notifications and alert management
"""
