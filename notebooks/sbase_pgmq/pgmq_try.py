# https://supabase.com/docs/guides/queues/api

# %%
from utils_common.db_utils.sbase_rest_ops import sbase_call_function
from supabase import create_client, Client
from config import pg_settings

client: Client = create_client(
    pg_settings.rest_url,
    pg_settings.rest_key
)


# %%
example_msg1 = {'command': '/dispatchResponse', 'order_number': '0f9d9e9b75fa4db7a1e34e0c53c6b986', 'dispatch_id': 115, 'status': 'accept', 'rider_id': '447448440754'}
example_msg2 = {'command': '/dispatchResponse', 'order_number': '8bac3a27f6354abcb3466269a719e13a', 'dispatch_id': 116, 'status': 'accept', 'rider_id': '447448440754'}

# %% Send batch msg to queue
client.schema('pgmq_public').rpc('send_batch', {
    "queue_name": 'rider_accept_q',
    "messages": [example_msg1, example_msg2]
}).execute()
# %% Send msg to queue
client.schema('pgmq_public').rpc('send', {"queue_name": 'rider_accept_q',
      "message": example_msg1
    }).execute()

client.schema('pgmq_public').rpc('send', {"queue_name": 'rider_accept_q',
      "message": example_msg2
    }).execute()

# %% Send batch msg to queue
client.schema('pgmq_public').rpc('send_batch', {
    "queue_name": 'rider_accept_q',
    "messages": [
        {"lohith": "rockStar1"},
        {"lohith": "rockStar1"}
    ]
}).execute()

# %% Read queue
client.rpc('read', {
    "queue_name": 'rider_accept_q',
    "sleep_seconds": 0,
    "n": 10
}).execute()
# %%

# %%
# await sbase_call_function(function_name="rider_accept_q.pop('rider_dispatch_accepted')", input_args={})


# %%