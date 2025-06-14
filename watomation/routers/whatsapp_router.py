# %%
"""
Router for WhatsApp integration using pywa_async for Ordelo delivery system
    . Instantiates WhatsApp client for use in routers
    . Imports config and FastAPI app context as needed
    . Follows pattern from fapp_ordelo_agent.py for WhatsApp instantiation
    . Prepares for future WhatsApp webhook/event endpoints

Functions/Classes:
    . wa (WhatsApp instance)
"""

from fastapi import APIRouter
from pywa_async import WhatsApp
from config import waba_business_settings
# from watomation.fapp_ordelo_agent import app

router = APIRouter(tags=["whatsapp_router"])

wa: WhatsApp = WhatsApp(
    token=waba_business_settings.token,
    server=router,
    verify_token=waba_business_settings.verify_token,
    phone_id=waba_business_settings.phone_id,
    callback_url=waba_business_settings.callback_url + "/whatsapp-router",
    webhook_challenge_delay=3,
    app_id=waba_business_settings.app_id,
    app_secret=waba_business_settings.app_secret,
    continue_handling=False,
    business_private_key=waba_business_settings.private_key,
    # business_private_key=open("/home/basal/PycharmProjects/OrdeloAgent/data/certs/private.pem").read(),
    business_private_key_password=waba_business_settings.private_key_password,
)
# %%
wa
# %% Future endpoints for WhatsApp webhook/event handling can be added here.
