--------------
-- Help
-- https://supabase.com/docs/guides/realtime?queryGroups=language&language=python
-- https://supabase.com/docs/guides/queues
---------
CREATE EXTENSION pgmq;
SELECT pgmq.create('rider_accept_q');
-- Enable RLS on the integrations - Queue - Settings -dashboard
-- Create Policy = "Allow anon and authenticated to access messages from queue"
-- Manage queue permissions on rider_accept_q

-- Send a message
SELECT * from pgmq.send(
  queue_name  => 'rider_accept_q',
  msg         => '{"foo": "bar1"}'
);

-- read 
SELECT * FROM pgmq.read(
  queue_name => 'rider_accept_q', vt =>0, qty => 100
)
order by enqueued_at desc;

01021769


/** Python
refer to /notebooks/sbase_pgmq/pgmq_try.py
from utils_common.db_utils.sbase_rest_ops import sbase_call_function
from supabase import create_client, Client
from config import pg_settings

client: Client = create_client(
    pg_settings.rest_url,
    pg_settings.rest_key
)

client.rpc('send', {"queue_name": 'rider_accept_q',
      "message": { "lohith": "rockStar" },
    }).execute()
**/

