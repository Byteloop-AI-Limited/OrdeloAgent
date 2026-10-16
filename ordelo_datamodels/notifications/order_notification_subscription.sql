CREATE TABLE IF NOT EXISTS public.order_notification_subscription (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    channel text NOT NULL,
    destination text, -- recipient phone for whatsapp_*; NULL for web_page
    detail_level text NOT NULL DEFAULT 'full' ::text,
    active boolean NOT NULL DEFAULT TRUE,
    source text NOT NULL, -- 'order_origin' | 'wa_handoff'
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    deactivated_at timestamp with time zone,
    CONSTRAINT order_notification_subscription_pkey PRIMARY KEY (id),
    CONSTRAINT order_notification_subscription_channel_check CHECK ((channel = ANY (ARRAY['whatsapp_restaurant'::text, 'whatsapp_agg'::text, 'web_page'::text]))),
    CONSTRAINT order_notification_subscription_detail_level_check CHECK ((detail_level = ANY (ARRAY['full'::text, 'status_only'::text]))),
    CONSTRAINT order_notification_subscription_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order (order_number) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ons_unique_active ON public.order_notification_subscription USING btree (order_number, channel, COALESCE(destination, ''::text))
WHERE
    active;
