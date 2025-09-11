# %%
import pickle

with open("/home/basal/PycharmProjects/OrdeloAgent/temp_store.pkl", "rb") as f:
    temp_store = pickle.load(f)
    print(temp_store)
# %%
payload = {
    "phone_num": "447476337721",
    "business_ref": "loarna ai ES",
    "phone_number_id": "813532365168347",
    "waba_id": "2242211042906352",
    "business_id": "716856174502571",
    "event_type": "FINISH",
    "code": "AQBTH1iC5KvFXMbAe1QcKt04oOB1X2X6ZOf3j-WZ3_k46nO7KbRXh3nEoFptdgd_8Qdnh_Q3Oheviyfj7buAqhnmIPdA_ypH4lrL363m-ScQYCgXZ9Gbc9ygcViAeIeUTJzJ7f2VabzrSPlVJosjv3sAd4qszWIPAxiz5TgycBKUbviBvXq1FA08LhY8wU78b3uyFs-q0EWaXhxMI-sI4zMEYqEA5eubOX5QUSZ8iw10MEsPmIksg_B9M6r4YgokjYLeoMqhTCOXYi6Z6uJU_8eCcoVXr-bMeW1RacsRC0G5vtn_2UvC1z_b0HoRp7oA5n7Wtg-AGiSW3WsEXSUW5iyetMy6YJLrOjvQQxKpcuFSs8zbLa3seS84N7tSbPbaA4jB9rYfFhsWLRzrmTxYd5a-3N03Bu5zPoUu6XDUA6T7bEhFLl5JUjIAB5f86BKtln0",
    "business_token": "EAAjaBvMpTDABPH7jLSvROI1lHUAEb0NFL3sEOPYa42LDHyCMmZACUEc7qwa2bOZCZCHiIQU4USTmXx4DD4hzw3MVvNPEUHqt2iBJZCkEWJbQ9kKRR5ZC242ksGDwymvgkRvUxe9Ine6ooXmhwNNsUZAt3RPgMtZBeIZBoyZBCsdyBBFleiY8nZCGSOdMVZApIndD9o3GjZCtsFY98CDToSzj0fglcWyuaQ7nCMduiKV7hbYvsvnsJ0Or4ndV5AkG3ZBdDoZA5ZAT0jgaoYTKQZDZD",
}


# %%
from config import client_ordelo

client_ordelo.table("waba_es").insert(payload).execute()
