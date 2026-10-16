CREATE OR REPLACE FUNCTION clear_dispatch ()
    RETURNS void
    AS $$
BEGIN
    -- delete dispatch so I can get the msg
    WITH latestRecord AS (
        SELECT
            order_number
        FROM
            delivery_dispatch
        ORDER BY
            dtts DESC
        LIMIT 1)
DELETE FROM delivery_dispatch dispatch
WHERE EXISTS (
        SELECT
            1
        FROM
            latestRecord
        WHERE
            order_number = dispatch.order_number);
END;
$$
LANGUAGE plpgsql;
