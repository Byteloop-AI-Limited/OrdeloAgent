# %%
import os
import requests
import json
import os
from pywa import WhatsApp
from pywa.types import SectionList, Section, SectionRow, Button, CallbackButton, Message, ButtonUrl
from pywa import filters as fil
from config.waba_setting import waba_business_settings
from pywa.types import Template as Temp
from config import logger
from pywa.types.templates import CarouselCard
# from pywa.types.templates import CarouselTemplate
# waba_phone_setting, waba_business_setting

# %%
wa = WhatsApp(
    business_account_id=1529867968356425,
    # token="temp",
    token="",
    phone_id=885001404688227,
    # server=app,
    verify_token="123456",
)

recipient = "447448440754"
# recipient = "447448440754"

# %%
wa.send_text(to=recipient, text='Hello World')

# %%
from utils_common.vec_ops.vec_search import get_product_sections
product_sections = get_product_sections()
wa.send_products(
    to=recipient,
    catalog_id=1760454711369294,
    title="Catalog",
    body="Here is the catalog",
        product_sections=product_sections,
    )

# %%
total=0
for section in product_sections:
    total+=len(section.skus)
total
# %%
wa.send_message(
    to=recipient,
    header="Header",
    text='PyWa [markdown](https://faq.whatsapp.com/539178204879377)',
    preview_url=False,
    buttons=[
    # Button(title='⬇️ Download', callback_data=f'https://pywa.readthedocs.io/'),
    # Button(title='💬 Comments', callback_data=f'cmnts'),
    # Button(title='🎬 Info', callback_data=f'info'),
]
)

# %% sending carousel
# from pywa.types import HeaderImage, QuickReplyButton, URLButton
from pywa.types.templates import CarouselCard, HeaderImage, QuickReplyButton, URLButton, Carousel

carousel = Carousel(cards=[
    card1 := CarouselCard(
        components=[
            hi1 := HeaderImage(example="https://example.com/card1.jpg"),
            qr1 := QuickReplyButton(text="Unsubscribe"),
            u1 := URLButton(text="Website", url="https://website.com?ref={{1}}", example="https://website.com?ref=card1"),
        ]
    ),
    card2 := CarouselCard(
        components=[
            hi2 := HeaderImage(example="https://example.com/card2.jpg"),
            qr2 := QuickReplyButton(text="Unsubscribe"),
            u2 := URLButton(text="Website", url="https://website.com?ref={{1}}", example="https://website.com?ref=card2"),
        ]
    ),
])
await wa.send_template(
    to=recipient,
    template=carousel,
)
# %%
sent_msg = wa.send_message(to=recipient, text="Hello World")
logger.info(f"Sent message: {sent_msg}")
# %% 
from utils_common.wa_send.wa_senders import confirm_delivery_address_wa
await confirm_delivery_address_wa(recipient, address="1 kingdowm street")

# %%get flows 
ywa.types.flows import FlowCategory

my_flows = wa.get_flows()
my_flows[0].update_metadata(
    name='Feedback',
    categories=[FlowCategory.SURVEY, FlowCategory.OTHER],
    endpoint_uri='https://loarna-ai-production.up.railway.app'
)

# %% Send documents 
from pywa import WhatsApp
import requests

res = requests.get('https://cdn.pixabay.com/photo/2014/10/01/10/44/animal-468228_1280.jpg')
wa.send_document(
    to=recipient,
    document=res.content,
    filename='animal.jpg',
    mime_type='image/jpeg',
)

# %% Send OwnTracks Config to drivers

import base64
import json

waypoints = [{
        "_type": "waypoint",
        "tst": 1708625557,
        "rid": "h0me",
        "desc": "home",
        "rad": 1,
        "lat": 51.354107,
        "lon": 0.095921
    }]

config = {
    "_type": "configuration",
    "mode": 3,
    "allowRemoteLocation": True,
    "usePassword": False,
    "monitoring": 2,
    "username": "iphone14",
    "password": "",
    "url": "https://live-track.byteloop.ai/pub",
    "locatorDisplacement": 2,
    "locatorInterval": 60,
    "waypoints": waypoints,
}

# Convert config to JSON string and encode to base64
config_json = json.dumps(config)
config_base64 = base64.b64encode(config_json.encode()).decode()
href = f"owntracks:///config?inline={config_base64}"

# Send as interactive message with URL button
wa.send_message(
    to=recipient,
    header="",
    text="...",
    reply_to_message_id=None,
    buttons=ButtonUrl(title="Start Job", url=href)
)

# %%
current_location="https://maps.google.com/?q=Order('1234')@51.354126,0.099301"

wa.send_message(
    to=recipient,
    text=f"Live location for your order",
    reply_to_message_id=None,
    buttons=ButtonUrl(title="Live Location", url=current_location)
)

# %%
wa.send_location(to=recipient, latitude=51.354126, longitude=0.099301)

# %%
wa.send_text(to=recipient, text='Hello World')

# %% payment reciept
def generate_whatsapp_receipt(order_summary):
    # Extracting order details
    order_id = order_summary["order_id"]
    order_type = order_summary["order_type"]
    recipient = order_summary["recipient"]
    items = order_summary["items"]

    # Building item details
    items_details = ""
    total_amount = 0
    for item in items:
        name = item["product_name"]
        price = item["price"]
        quantity = item["quantity"]
        total_price = price * quantity
        total_amount += total_price
        items_details += f"▫️ *{name}* x{quantity} £{total_price:.2f} "

    return [order_id, order_type, items_details, total_amount]

order_summary = {
    "order_id": "EDJJ-26",
    "order_type": "Paid Collection",
    "payment_status": "awaiting_payment",
    "recipient": "447448440754",
    "thread_id": "39e55759-c10f-44de-8510-25f00682ec8f",
    "items": [
        {
            "product_name": "Cheesecake",
            "price": 5.95,
            "quantity": 2
        },
        {
            "product_name": "Meen Mulakittathu Curry",
            "price": 13.95,
            "quantity": 2
        }
    ],
    "currency": "GBP"
}

# Generate receipt
receipt = generate_whatsapp_receipt(order_summary)
print(receipt)

# %%
wa.send_template(
    to=recipient,
    template=Temp(
        name='payment_reciept_elai',
        language=Temp.Language.ENGLISH_UK,
        body=[
            Temp.TextValue(value=receipt[0]),
            Temp.TextValue(value=receipt[1]),
            Temp.TextValue(value=receipt[2]),
            Temp.TextValue(value=receipt[3]),
        ],
    )  
)

# %%
import tenacity
# %%

wa.send_template(
    to=recipient,
    template=Temp(
        name='request_payment',
        language=Temp.Language.ENGLISH_UK,
        body=[
            Temp.TextValue(value='10hith'),
            Temp.TextValue(value='pubg-14'),
        ],
        buttons=[
            Temp.UrlButtonValue(value="c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl"),
            # Temp.TextValue(value="https://checkout.stripe.com/c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl")
        ],
    ),
)

# %%
wa.send_template(
    to="447850773336",
    template=Temp(
        name='demo_tryout',
        language=Temp.Language.ENGLISH
    )
)

# %%
Temp(
        name='order_management_3',
        language=Temp.Language.ENGLISH_US,
        body=[
            Temp.TextValue(value='Rahul'),
            Temp.TextValue(value='123'),
        ],
        buttons=[
            Temp.UrlButtonValue(value="c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl"),
            # Temp.TextValue(value="https://checkout.stripe.com/c/pay/cs_test_a1D1wkHFSLtrEZhTnVnfiztBDNIUvVvfeWzkhnO97bWEDRRx0wZE8HpiOp#fidkdWxOYHwnPyd1blpxYHZxWjA0VE1dcGlCYz1JYkw3UHZxdG9TSHxMc2YxbFNpPU5SNWltYlBUfUNxdHx3ZmhtQlZxVF9TfEZDNUZwTFB0XX03PEs8cmswdnZRfG5TcFNxN0lsdG5rQWo1NTVWSU03YVdcbicpJ2N3amhWYHdzYHcnP3F3cGApJ2lkfGpwcVF8dWAnPyd2bGtiaWBabHFgaCcpJ2BrZGdpYFVpZGZgbWppYWB3dic%2FcXdwYHgl")
        ],
    ).to_dict()
# %%
# This is the whatsapp link to start a conversation
markdown_text = """
https://wa.me/447424334783?text=Hello%2C%20I%20would%20like%20more%20information
"""
# wa.send_message(
#     to=recipient,
#     text=markdown_text
# )

wa.send_message(
    to=recipient,
    text='PyWa [markdown](https://faq.whatsapp.com/539178204879377)',
    preview_url=False,
    buttons=[
    Button(title='⬇️ Download', callback_data=f'https://pywa.readthedocs.io/'),
    Button(title='💬 Comments', callback_data=f'cmnts'),
    Button(title='🎬 Info', callback_data=f'info'),
]
)

# wa.send_bu(
#     to=recipient,
#     text='PyWa [markdown](https://faq.whatsapp.com/539178204879377)',
#     preview_url=False,
# )

# wa.send_image(
#     to=recipient,
#     image=f'https://pywa.readthedocs.io/',
#     caption='Chandler Jokes | Friends • 2.9M views • 1 year ago',
#     footer='⚡ Powered by PyWa',
#     buttons=[
#         Button(title='⬇️ Download', callback_data=f'https://pywa.readthedocs.io/'),
#         Button(title='💬 Comments', callback_data=f'cmnts'),
#         Button(title='🎬 Info', callback_data=f'info'),
#     ]
# )
# wa.get_commerce_settings()
# wa.get_business_phone_number()

# https://graph.facebook.com/v17.0/{waba_id}/catalogs

# %% Getting feed id
# url = "https://graph.facebook.com/v21.0/365315793337549/product_feeds"
# # 1005775587696145
# payload={}
# response = requests.get(url, headers=waba_cat_setting.cat_headers, data=json.dumps(payload))
# response.text

# %% send catalog 
wa.send_catalog(
    to=recipient,
    body='Check out our catalog!',
    # footer='Powered by PyWa',
    thumbnail_product_sku='123',
)

# %% send location 
wa.send_location(
    to=recipient,
    latitude=51.2626545707999,
    longitude=-1.0845731448928566,
    name='Elai Restaurant',
    address='Unit 1, Anchor Court, 28 London St, Basingstoke RG21 7NY',
)
# %% Getting Commerce settings

url = "https://graph.facebook.com/v21.0/365315793337549/whatsapp_commerce_settings"

# Construct the headers using the API key variable
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {waba_business_settings.token}",  # Using f-string for cleaner interpolation
}

# Payload for the request
payload = {}

response = requests.get(url, headers=headers, data=json.dumps(payload))
response.text
