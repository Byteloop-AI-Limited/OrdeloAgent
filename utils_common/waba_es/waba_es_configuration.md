# WhatsApp Embedded Signup Configuration Guide

## Embedded Signup Configuration Settings

Login variation
To choose a different login variation, create a new configuration.
WhatsApp Embedded Signup
Access token
Type of token of this configuration. Learn about access tokens.
System-user access token
Access token expiration
This is when this token will expire. Learn about token expiration and refresh.
Token will never expire
Assets
Users are required to give this app access to:
WhatsApp accounts
Advanced Tasks
The following advanced tasks would be performed as part of the token creation. Learn about advanced tasks.
manage
​
develop
​
manage_templates
​
view_phone_assets
​
manage_phone_assets
​
view_templates
​
messaging
​
Permissions
Users are required to give this app the following permissions:
​
Permissions in standard access will only be requested from people with roles on this app.
Learn about access levels.
business_management
catalog_management
whatsapp_business_management
whatsapp_business_messaging

---

## !!! Actions — Assign New WABA to System User !!!

After a new WhatsApp Business Account is created via Embedded Signup, you must assign it to the system user so the existing system access token can manage it.

1. Go to the **Tech Provider WA Business** (ByteLoop AI Limited) in Meta Business Suite.
2. Navigate to **System Users**.
3. Select the WABA system user — ID: `61570427480113`.
4. Click **Assign Assets**.
5. Under **WA Accounts**, find and select the **newly created** WhatsApp Business Account.
6. Assign the appropriate permissions and confirm.
7. You can now use the existing **system access token** (`bloop_waa_token`) to manage the new WABA — no new token is needed.