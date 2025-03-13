# in data path 
# openssl genrsa -des3 -out private.pem 2048 (passphrase: 14)
# openssl rsa -in private.pem -outform PEM -pubout -out public.pem

# Encode your private key first (on your local machine) - update it to BLOOP_WAA_PRIVATE_KEY_b64 in .env
# cat private.pem | base64 -w 0 > private_b64

# %%
from config import _async_wa_client

# %% update the public key to waba

await _async_wa_client.set_business_public_key(open("/home/basal/PycharmProjects/OrdeloAgent/data/certs/public.pem").read())


# %%
open("/home/basal/PycharmProjects/OrdeloAgent/data/certs/private.pem").read()
# %%
from config import waba_business_settings

waba_business_settings.
