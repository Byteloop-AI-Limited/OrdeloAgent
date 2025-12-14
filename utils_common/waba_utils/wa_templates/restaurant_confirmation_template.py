"""
WhatsApp template definitions for restaurant confirmations
  . Provides static Template objects for WhatsApp outreach
  . Configures header, body, and quick reply settings for order updates
  . Ensures metadata (language, category, params) comply with Pywa + WABA
  . Sends restaurant pickup time confirmation templates with order details
  Functions/Classes:
    . send_restaurant_pickup_time_confirmation
"""

# %%
import json
import os
from importlib import reload
from typing import Sequence

import requests
from pywa import WhatsApp
from pywa import filters as fil
from pywa.types import (
    Button,
    ButtonUrl,
    CallbackButton,
    Message,
    Section,
    SectionList,
    SectionRow,
    Template,
)
from pywa.types import Template as Temp
from pywa.types.templates import *
from pywa.types.templates import CarouselCard

import config.waba_setting

# from pywa.types.templates import CarouselTemplate
# waba_phone_setting, waba_business_setting
from config import _sync_wa_client as wa
from config import logger

# Reload to pick up any changes (e.g., app_id added)
from config.waba_setting import _sync_wa_client as wa
from config.waba_setting import waba_business_settings
from utils_common.waba_utils.wa_senders import CallbackButtonData

# %%


def create_template(template: Template):
    return wa.create_template(template, app_id=waba_business_settings.app_id)


# %%

restaurant_order_confirmation = Template(
    name="restaurant_order_confirmation",
    language=TemplateLanguage.ENGLISH_UK,
    category=TemplateCategory.MARKETING,
    parameter_format=ParamFormat.NAMED,
    components=[
        hdr_offer := HeaderText(
            text="Order {{order_number_amount}}",
            order_number_amount="12345 £25.00",
        ),
        bdy_offer := BodyText(
            "Hi \nOrder Details : {{order_items}} \nPlease Accept or Decline:\n",
            order_items="2x Butter Chicken, 2x Naan",
        ),
        Buttons(
            buttons=[
                qrb_accept := QuickReplyButton(
                    text="Accept",
                ),
                qrb_decline := QuickReplyButton(
                    text="Decline",
                ),
            ]
        ),
    ],
)

# have a create template function
# %%
# create_template(restaurant_order_confirmation)


# %%


# this can be replaced by send_restaurant_order_confirmation in wa_adhoc_run.py
def send_restaurant_order_confirmation_templated(
    recipient: str,
    order_number: str,
    order_amount: str,
    order_items: str,
    order_time: int,
    order_type: str,
) -> Message:
    """Send the restaurant_order_offer template."""
    accept_button = CallbackButtonData(
        action="/RestaurantOrder-Accept",
        order_number=order_number,
        order_time=order_time,
    )
    decline_button = CallbackButtonData(
        action="/RestaurantOrder-Decline",
        order_number=order_number,
        order_time=order_time,
    )

    if order_type == "delivery":
        order_type_icon = " 🚚 "
    elif order_type == "takeaway":
        order_type_icon = " 🥡 "
    return wa.send_template(
        to=recipient,
        name="restaurant_order_confirmation",
        language=TemplateLanguage.ENGLISH_UK,
        params=[
            HeaderText.params(
                order_number_amount=order_number
                + " "
                + order_amount
                + order_type_icon
                + order_type.capitalize()
            ),
            bdy_offer.params(
                order_items=order_items,
            ),
            qrb_accept.params(
                callback_data=accept_button.model_dump_json(),
                index=0,
            ),
            qrb_decline.params(
                callback_data=decline_button.model_dump_json(),
                index=1,
            ),
        ],
    )


# %%

# response = send_restaurant_order_confirmation(
#     recipient="447448440754",
#     order_number="ELAS-ZVEO-29",
#     order_amount="£25.00; Takeaway",
#     order_items="2x Butter Chicken, 2x Naan",
#     order_time=12345,
# )

# %%
# print(response.id)

# %% Pickup template - works, but not used. Reference for future template.

restaurant_pickup_time_confirmation = Template(
    name="restaurant_pickup_time3",
    language=TemplateLanguage.ENGLISH_UK,
    category=TemplateCategory.MARKETING,
    parameter_format=ParamFormat.NAMED,
    components=[
        hdr := HeaderText(
            text="Order {{order_number}}",
            order_number="12345",
        ),
        bdy := BodyText(
            "Hi {{name}}, \nOrder Details: \n{{order_items}}.\n"
            "Pickup Time 1: *{{pickup_one}}*\n"
            "Pickup Time 2: *{{pickup_two}}*\n"
            "Pickup Time 3: *{{pickup_three}}*\n\n"
            "Please Select Pickup time:\n",
            name="John Doe",
            order_items="2x Paneer Tikka, 1x Garlic Naan",
            pickup_one="12:00 PM",
            pickup_two="12:30 PM",
            pickup_three="1:00 PM",
        ),
        Buttons(
            buttons=[
                qrb_one := QuickReplyButton(
                    text="Pickup Time 1",
                ),
                qrb_two := QuickReplyButton(
                    text="Pickup Time 2",
                ),
                qrb_three := QuickReplyButton(
                    text="Pickup Time 3",
                ),
            ]
        ),
    ],
)
# %%

# wa.create_template(
#     restaurant_pickup_time_confirmation, app_id=waba_business_settings.app_id
# )

# %%
# send template


def send_restaurant_pickup_time_confirmation(
    *,
    recipient: str,
    order_number: str,
    name: str,
    order_items: str,
    pickup_one: str,
    pickup_two: str,
    pickup_three: str,
) -> Message:
    """Send the restaurant_pickup_time2 template with order and pickup time details."""

    return wa.send_template(
        to=recipient,
        name="restaurant_pickup_time2",
        language=TemplateLanguage.ENGLISH_UK,
        params=[
            # HeaderText(text="Order {{order_number}}").params(
            #     order_number=order_number,
            # ),
            HeaderText.params(order_number=order_number),
            bdy.params(
                name=name,
                order_items=order_items,
                pickup_one=pickup_one,
                pickup_two=pickup_two,
                pickup_three=pickup_three,
            ),
            qrb_one.params(callback_data="contact-support", index=0),
            qrb_two.params(callback_data="contact-support", index=1),
            qrb_three.params(callback_data="contact-support", index=2),
        ],
    )


# # %%
# send_restaurant_pickup_time_confirmation(
#     recipient="447448440754",
#     order_number="12345",
#     name="John Doe",
#     order_items="2x Paneer Tikka, 1x Garlic Naan",
#     pickup_one="12:00 PM",
#     pickup_two="12:30 PM",
#     pickup_three="1:00 PM",
# )
