# Delivery Service Flow

```mermaid
sequenceDiagram
    participant Customer
    participant DeliveryDetail as Delivery Detail Table
    participant DeliveryDispatch as Delivery Dispatch Table
    participant WebHook as Webhook Service
    participant WhatsApp as WhatsApp Service
    participant Rider
    participant Graph as AI Agent Graph

    Customer->>DeliveryDetail: Place Order
    Note over DeliveryDetail: New record created
    
    DeliveryDetail->>WebHook: Trigger delivery-dispatch webhook
    Note over WebHook: POST /delivery-hooks/delivery-dispatch
    
    WebHook->>DeliveryDispatch: Create dispatch record
    DeliveryDispatch->>WhatsApp: Send job offer to rider
    Note over WhatsApp: Includes order details & buttons
    
    WhatsApp->>Rider: Job offer message
    Rider->>WhatsApp: Accept job
    
    WhatsApp->>DeliveryDispatch: Check job availability
    alt Job is available
        DeliveryDispatch->>DeliveryDispatch: Update status to 'accepted'
        DeliveryDispatch->>DeliveryDetail: Update status
        Note over DeliveryDetail: Status update triggers webhook
        
        DeliveryDetail->>WebHook: Trigger delivery-detail-update webhook
        Note over WebHook: POST /delivery-hooks/delivery-detail-update
        
        WebHook->>Graph: Initialize AI Agent Graph
        Note over Graph: Start live tracking & rider assistance
    else Job already taken
        WhatsApp->>Rider: Job no longer available
    end
```

## Flow Description

1. **Order Creation**
   - Customer places an order
   - New record created in DeliveryDetail table

2. **Initial Webhook**
   - Insert triggers delivery-dispatch webhook
   - Creates dispatch record
   - Sends job offer to rider via WhatsApp

3. **Rider Response**
   - Rider receives job offer with accept/decline buttons
   - On acceptance, system checks job availability

4. **Job Assignment**
   - If job is available:
     - Update dispatch status to 'accepted'
     - Update delivery detail status
     - Trigger delivery-detail-update webhook

5. **AI Agent Initialization**
   - Webhook initializes AI Agent Graph
   - Graph starts live tracking
   - AI Agent begins assisting rider through delivery process
