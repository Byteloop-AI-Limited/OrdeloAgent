# %%
import os
import requests
import json
import os
from pywa import WhatsApp
from pywa.types import (
    SectionList,
    Section,
    SectionRow,
    Button,
    CallbackButton,
    Message,
    ButtonUrl,
)
from pywa import filters as fil
from config.waba_setting import waba_business_settings
from pywa.types import Template as Temp
from config import logger
from pywa.types.templates import CarouselCard
from config import _sync_wa_client as wa
# from pywa.types.templates import CarouselTemplate
# waba_phone_setting, waba_business_setting

# %%
# wa = WhatsApp(
#     business_account_id=1529867968356425,
#     # token="temp",
#     token="",
#     phone_id=885001404688227,
#     # server=app,
#     verify_token="123456",
# )

recipient = "447448440754"
# recipient = "447448440754"

waba_business_settings.phone_id
# %%

wa.api.send_raw_request(
    method="POST",
    endpoint=f"/{waba_business_settings.phone_id}/message_templates",
    json={"to": recipient, "messaging_product": "whatsapp", **carousel.to_dict()},
)
# %%
carousel_dict = {
    "cards": [
        {
            "components": [
                {
                    "type": "header",
                    "format": "<CARD_HEADER_FORMAT>",
                    "example": {"header_handle": ["<CARD_HEADER_ASSET_HANDLE>"]},
                },
                {
                    "type": "buttons",
                    "buttons": [
                        {
                            "type": "quick_reply",
                            "text": "<QUICK_REPLY_BUTTON_LABEL_TEXT>",
                        },
                        {
                            "type": "url",
                            "text": "<URL_BUTTON_LABEL_TEXT>",
                            "url": "<URL_BUTTON_URL>",
                            "example": ["<URL_BUTTON_URL_VARIABLE_EXAMPLE>"],
                        },
                        {
                            "type": "phone_number",
                            "text": "<PHONE_NUMBER_BUTTON_LABEL_TEXT>",
                            "phone_number": "<PHONE_NUMBER>",
                        },
                    ],
                },
            ]
        }
    ]
}
wa.api.send_raw_request(
    method="POST",
    endpoint=f"/{waba_business_settings.phone_id}/messages",
    json={
        "to": recipient,
        "type": "carousel",
        "cards": carousel_dict,
        "messaging_product": "whatsapp",
    },
)


# %% sending carousel
# from pywa.types import HeaderImage, QuickReplyButton, URLButton
from pywa.types.templates import (
    CarouselCard,
    HeaderImage,
    QuickReplyButton,
    URLButton,
    Carousel,
)

carousel = Carousel(
    cards=[
        card1 := CarouselCard(
            components=[
                hi1 := HeaderImage(example="https://example.com/card1.jpg"),
                qr1 := QuickReplyButton(text="Unsubscribe"),
                u1 := URLButton(
                    text="Website",
                    url="https://website.com?ref={{1}}",
                    example="https://website.com?ref=card1",
                ),
            ]
        ),
        card2 := CarouselCard(
            components=[
                hi2 := HeaderImage(example="https://example.com/card2.jpg"),
                qr2 := QuickReplyButton(text="Unsubscribe"),
                u2 := URLButton(
                    text="Website",
                    url="https://website.com?ref={{1}}",
                    example="https://website.com?ref=card2",
                ),
            ]
        ),
    ]
)
carousel.to_dict()
