Which options best describe your business? Select all that apply.
If your business owns multiple companies or brands, select the option that best describes the part of your business that provides services of a Tech Provider.

Agency

Freelancer

Consultancy

SaaS Platform

Other
How will your business use Platform Data (i.e., any info or data you obtain from us) to enable a product or service on behalf of your clients?
Include detail about the service being provided, how Platform Data is being used to provide that service and how clients will use that service. Keep your explanation short and avoid using technical jargon.
Free form text input
Does your business manage multiple business portfolios?
If yes, you will be asked to provide the business portfolio IDs for the businesses you manage.
Radio List

No

Yes
Provide a link to your website.
Make sure to provide a valid URL to a complete website showing the service you described above and details of the business providing the service.
Draft saved on Tue 2:08 PM



-- Verification
Usecase: We use WhatsApp Cloud API webhooks to receive incoming message content and sender metadata, which powers an AI-driven chat agent for lead capture

Service Description: The service provided automation mainly, focussing on early engagement with customers arriving from WA. Given its an AI solution, we also provide Human in the loop workflows and implement guardrails.

How we use platform Data:
1. Incoming messages and metadata - The WA profile name is used in the conversation to provide a personalized experience.
2. Messages and State management:
    2.1 For effective conversations, Messages are stored only for a given session. Inactivity of more than 5 mins will start a new session. Messages are stored on cloud provider within the UK (Supabase) and cleared on a session reset.
    2.2 The messages stack within an active session is sent to AI to generate the response. Again, the services provided by the LLM provider is within the UK (Azure Openai)

3. Information sharing:
NO information is shared to external parties. In cases of Human escalation, i.e an explicit request to get in touch with business, the lead is passed to the business owner.


