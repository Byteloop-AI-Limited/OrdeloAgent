# Use Case Description

Provide a simple AI powered chat agent for businesses for lead capture. The AI chat agent will hold a natural conversation with the user in English. 
Here is how the conversation turns are managed:
1. User sends a WhatsApp message to the business (TestNumber - `+1 555 139 6959`)
2. The webhook is configured to receive these messages. 
3. AI Agent runs and the response is sent to the user but calling a POST request to graph api, provided by`WhatApp Cloud Api`. [Evidenced in the logs]

`Human in the loop` - The entier conversation is *statefull* and aimed at having a maximum of 12-15 turns. Anything more will direct the customer to the business owner. 

`Guardrails` - The AI chat agent is designed to maintain a *high quality* conversation with the customer, staying on topic, understanding the context and intent of the customer's message,

### Additional Notes for the `App Reviewer`:
1. This markdown file is used as `annotations` to the actions being performed in the video.
2. App for this use case is the interactive notebook running below.
3. Unable to create test users. https://developers.facebook.com/docs/development/build-and-test/test-users

-----------------
# Demonstrate the use of permission `whatsapp_business_management`.

## Demostration of read, create and delete of WhatsApp Message Templates using the Facebook Graph API. All api calls are evidenced in the `logs` 
- business account id: `519360677921630` displayed in the notebook/code and in Business settings

1. Show existing templates on `WhatsApp Manager`, dropdown to select the right business WABA account
2. Run code to create a new template, refresh the page to see the new template
3. Get the list of templates along with their status. New template should be in the list
4. Delete a template, refresh the page to show the template has been deleted

## Show sending a template message
1. Send default template to user

### The demo is based thorough review of documentation available. If anything is missed, kindly feedback and we will action.


-------
# Video 1: Demonstrate Sending and receiving WhatsApp Message (whatsapp_business_messaging)
## Webhook Registration
1. Evidence the test number that is being used
2. Show webhook registration for this test number (appId is same for `Api setup` and `Configuration` pages)
3. Verify the webhook. App `logs` to display the successful verification of the webhook.

## Sending and receiving a message via graph api
1. User messages the business (TestNumber - `+1 555 139 6959`)
2. App `logs` to display the received message and the number that sent the message.
3. App responds
    - 3.1. Show use of WABA features like `indicate typing`. Such features are not offered by few of the BSPs
    - 3.2. `logs` to display the `POST` request to graph api 
    - 3.3. Show message appearing on the user's WhatsApp (web)
    - 3.4. Show user being addressed with their *Whatsapp profile* name

4. Demonstrate conversation robustness
    - 4.1. User requests agent to perform a random task.
    

5. Demonstrate the `statefull` conversation.
    - 4.1. User to ask 'Whats my name?', 'how do you know my name?'.

### The demo is based thorough review of documentation available. If anything is missed, kindly feedback and we will action.
--
---------------------------------------
--
--
--
