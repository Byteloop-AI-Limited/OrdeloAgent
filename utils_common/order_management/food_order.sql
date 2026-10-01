CREATE SEQUENCE daily_seq START WITH 20;
-- drop sequence daily_seq;
-- Table to store the last date when the sequence was used
CREATE TABLE IF NOT EXISTS daily_seq_last_value (
    last_value_date DATE PRIMARY KEY
);

-- drop function get_next_daily_seq;
-- Function to get the next value from the sequence based on the current date
CREATE OR REPLACE FUNCTION get_next_daily_seq(input_date DATE)
RETURNS INTEGER AS $$DECLARE
    seq_value INTEGER;
    date_exists BOOLEAN;
BEGIN
    -- Check if the input_date already exists in the table
    SELECT EXISTS(SELECT 1 FROM daily_seq_last_value WHERE last_value_date = input_date) INTO date_exists;

    -- If the input date does not exist, reset the sequence and insert the new date
    IF NOT date_exists THEN
        PERFORM setval('daily_seq', 20, false);
        INSERT INTO daily_seq_last_value (last_value_date) VALUES (input_date);
    END IF;

    -- Get the next value from the sequence
    seq_value := nextval('daily_seq');
    RETURN seq_value;
END;$$ LANGUAGE plpgsql;

-- DROP TABLE public.food_order CASCADE;
CREATE TABLE public.food_order (
    order_number TEXT PRIMARY KEY,
    order_id TEXT UNIQUE,
    seq_id INTEGER,
    recipient TEXT NOT NULL,
    notes TEXT NULL,
    thread_id TEXT NOT NULL,
    action TEXT NOT NULL,
    total_price FLOAT NOT NULL,
    final_order_value FLOAT NULL,
    rest_cost FLOAT NULL,
    service_charge FLOAT NULL,
    delivery_fee FLOAT NULL,
    small_order_fee FLOAT NULL,
    commission_rate FLOAT NULL,
    payment_status TEXT NOT NULL,
    order_dt DATE DEFAULT CURRENT_DATE, 
    order_dtts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


-- Create the OrderItem table
CREATE TABLE public.order_item (
    order_id TEXT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    modifications TEXT[] NULL,
    FOREIGN KEY (order_id) REFERENCES public.food_order(order_id) ON DELETE CASCADE
);

ALTER TABLE public.order_item
    ADD COLUMN IF NOT EXISTS modifications TEXT[] NULL;

-- Create the OrderItem table
CREATE TABLE public.order_item_v2 (
    order_id TEXT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    modifications TEXT[] NULL,
    FOREIGN KEY (order_id) REFERENCES public.food_order(order_id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- 001  food_order: origin channel, storefront, idempotency key   (D15, D28)
-- ---------------------------------------------------------------------------
ALTER TABLE public.food_order
  ADD COLUMN IF NOT EXISTS origin_channel TEXT NOT NULL DEFAULT 'whatsapp'
      CONSTRAINT food_order_origin_channel_chk CHECK (origin_channel IN ('whatsapp','web')),
  ADD COLUMN IF NOT EXISTS storefront TEXT NOT NULL DEFAULT 'direct'
      CONSTRAINT food_order_storefront_chk CHECK (storefront IN ('direct','ordelo')),
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT NULL;   -- used by web create-order (R3)

CREATE UNIQUE INDEX IF NOT EXISTS food_order_idempotency_key_uq
  ON public.food_order (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- origin_channel and storefront are written once at insert and never change.
CREATE OR REPLACE FUNCTION public.forbid_food_order_origin_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.origin_channel IS DISTINCT FROM OLD.origin_channel THEN
    RAISE EXCEPTION 'food_order.origin_channel is immutable (order %)', OLD.order_number;
  END IF;
  IF NEW.storefront IS DISTINCT FROM OLD.storefront THEN
    RAISE EXCEPTION 'food_order.storefront is immutable (order %)', OLD.order_number;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS food_order_origin_immutable ON public.food_order;
CREATE TRIGGER food_order_origin_immutable
  BEFORE UPDATE OF origin_channel, storefront ON public.food_order
  FOR EACH ROW EXECUTE FUNCTION public.forbid_food_order_origin_change();


-- %% cascaded drop
DROP TABLE IF EXISTS OrderItem;
DROP TABLE IF EXISTS FoodOrder;

select * from food_order where order_number like 'SFCS-ESUY-24';
select * from order_item_v2 where order_id = 'ESUY-24';
select * from order_item where order_id = 'HXKS-29';

-- delete from order_item where order_id = 'ESUY-24';