-- job_process_owntracks.sql
-- Batch process OwnTracks messages into rider_location and rider_location_event tables
CREATE OR REPLACE FUNCTION public.job_process_owntracks()
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  rec_loop RECORD;
  msg_ids bigint[];
  v_msg_id bigint;
  v_processed_count INT := 0;

BEGIN
  WITH msgs AS (
    SELECT msg_id, message::jsonb AS msg
      FROM pgmq.read('owntracks', 0, 1000)
  ),
  parsed AS (
    SELECT
      msg->>'_type' AS _type,
      msg->>'topic' AS topic,
      (regexp_match(msg->> 'topic', 'owntracks/([^/]+)/'))[1] AS rider_id,
      (msg->>'tst')::bigint AS tst,
      to_timestamp((msg->>'tst')::bigint) AS tst_dtts,
      msg
    FROM msgs
  ),
  location_rows AS (
    SELECT
      topic,
      p.rider_id,
      inflight.customer_id,
      inflight.order_number,
      (msg->>'acc')::int AS acc,
      (msg->>'alt')::int AS alt,
      (msg->>'batt')::int AS batt,
      (msg->>'lat')::float AS lat,
      (msg->>'lon')::float AS lon,
      (msg->>'tst')::int AS tst,
      msg->>'tid' AS tid,
      msg->>'conn' AS conn,
      (SELECT array_agg(val) FROM jsonb_array_elements_text(msg->'inregions') AS elem(val)) AS inregions,
      (SELECT array_agg(val) FROM jsonb_array_elements_text(msg->'inrids') AS elem(val)) AS inrids,
      (msg->>'created_at')::int AS created_at,
      (msg-> 'm')::int AS m,
      tst_dtts
    FROM parsed p
    JOIN delivery_inflight inflight ON inflight.rider_id = p.rider_id
    WHERE p._type = 'location'
  ),
  transition_rows AS (
    SELECT
      topic,
      p.rider_id,
      inflight.customer_id,
      inflight.order_number,
      msg->>'rid' AS rid,
      msg->>'event' AS event
    FROM parsed p
    JOIN delivery_inflight inflight ON inflight.rider_id = p.rider_id
    WHERE p._type = 'transition'
  ), loc_insert AS (
  -- Use a single WITH statement for both inserts to maintain CTE scope
    INSERT INTO rider_location SELECT * FROM location_rows
    RETURNING 1
  ), event_insert AS (
    INSERT INTO rider_location_event(topic, rider_id, customer_id, order_number, rid, event)
    SELECT * FROM transition_rows
    RETURNING 1
  ), msg_id_collect AS (
    SELECT array_agg(msg_id) AS ids FROM msgs
  )
  SELECT ids INTO msg_ids FROM msg_id_collect;
  
  -- Archive processed messages
  IF msg_ids IS NOT NULL THEN
    v_processed_count := array_length(msg_ids, 1);
    FOREACH v_msg_id IN ARRAY msg_ids LOOP
      PERFORM pgmq.archive('owntracks', v_msg_id);
    END LOOP;
  END IF;

  RETURN v_processed_count;
END;
$$;

-- pg_cron job 'job_process_owntracks' (live schedule: 30 seconds, active). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_process_owntracks', '30 seconds', $cron$SELECT public.job_process_owntracks()$cron$);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- / *
-- """
-- Processes OwnTracks messages from a queue into location tables.
--   . Reads messages from pgmq queue 'owntracks'
--   . Processes location data into rider_location table
--   . Processes transition events into rider_location_event table (always inserts new records, no upsert)
--   . Archives processed messages
--   . Returns the count of processed messages
-- Functions:
--   . job_process_owntracks
-- """
-- */;
