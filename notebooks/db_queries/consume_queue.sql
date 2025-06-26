WITH owntracks AS (
    SELECT 
    msg_id,
    message ->> 'id' AS id,
    message->>'topic' AS topic,
    (regexp_match(message->>'topic', 'owntracks/([^/]+)/([^-]+)-([^/]+)'))[1] AS rider_id,
    (message->>'acc')::INT AS acc,
    (message->>'alt')::INT AS alt,
    (message->>'batt')::INT AS batt,
    (message->>'lat')::float AS lat,
    (message->>'lon')::float AS lon,
    (message->>'t')::varchar AS t,
    (message->>'tst')::BIGINT AS tst,
    (message->>'tid')::varchar AS tid,
    (message->>'conn')::varchar AS conn,
    (message->'inregions') AS inregions,
    (message->'inrids') AS inrids,
    (message->>'created_at')::bigint AS created_at,
    (message->'m')::int AS m,
    message->>'_type' AS type,
    to_timestamp((message->>'tst')::BIGINT) AS tst_dtts
FROM pgmq_public.read('owntracks', 0, 100)
)
SELECT 
    owntracks.topic,
    owntracks.rider_id,
    inflight.customer_id,
    inflight.order_number,
    owntracks.acc,
    owntracks.alt,
    owntracks.batt,
    owntracks.lat,
    owntracks.lon,
    owntracks.t,
    owntracks.tst,
    owntracks.tid,
    owntracks.conn,
    owntracks.type,
    owntracks.inrids,
    owntracks.inregions,
    owntracks.created_at,
    owntracks.m,
    owntracks.msg_id,
    tst_dtts
FROM owntracks 
LEFT OUTER JOIN delivery_inflight AS inflight on owntracks.rider_id = inflight.rider_id
WHERE owntracks.type = 'location'
limit 100;

select * from delivery_inflight limit 100;

select * from rec;

select * from rider_location;
-- Query for transition events
WITH owntracks AS (
    SELECT 
        msg_id,
        message->>'topic' AS topic,
        message->>'_type' AS type,
        (regexp_match(message->>'topic', 'owntracks/([^/]+)/'))[1] AS rider_id,
        (message->>'event') AS event,
        (message->>'rid') AS rid,
        (message->>'tst')::BIGINT AS tst,
        to_timestamp((message->>'tst')::BIGINT) AS dtts
    FROM pgmq_public.read('owntracks', 0, 100)
)
SELECT 
    owntracks.topic,
    owntracks.rider_id,
    inflight.customer_id,
    inflight.order_number,
    owntracks.rid,
    owntracks.event,
    owntracks.tst,
    owntracks.dtts
FROM owntracks 
LEFT JOIN delivery_inflight AS inflight ON owntracks.rider_id = inflight.rider_id
WHERE owntracks.type = 'transition'
LIMIT 100;

-- example paylod for transition event

{
    "lon": 0.096501,
    "acc": 2,
    "wtst": 1739801838,
    "event": "enter",
    "rid": "cust",
    "desc": "home",
    "topic": "owntracks/447448440754/447448440754-e153845d621d497ea780a9ce5647d822/event",
    "lat": 51.354255,
    "t": "c",
    "tst": 1739802742,
    "tid": "23",
    "_type": "transition"
}