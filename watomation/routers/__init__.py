"""
Router modules for WhatsApp automation and webhook handlers
    . Contains FastAPI routers for delivery, takeaway, location and alert webhooks
    . Handles delivery dispatch notifications and tracking
    . Handles takeaway restaurant confirmation and pickup-time notifications
    . Processes location updates and rider tracking webhooks
    . Manages Twilio webhook integrations
  Routers:
    . delivery_hooks - Delivery dispatch and inflight tracking webhooks
    . takeaway_hooks - Takeaway restaurant confirmation webhooks
    . location_hooks - Live location and rider tracking webhooks
    . twilio_webhook - Twilio integration webhooks
"""
