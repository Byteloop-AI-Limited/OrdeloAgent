-- Forward-compatible schema update for databases where the initial WaLocation
-- migration was already applied before caller-supplied callbacks were added.
-- New requests require callback_url in application code; historical rows stay
-- unroutable until an operator chooses a safe callback destination.

BEGIN;

ALTER TABLE public.wa_location_request
    ADD COLUMN IF NOT EXISTS callback_url TEXT;

ALTER TABLE public.wa_location_request
    ADD CONSTRAINT wa_location_request_callback_url_length_ck
    CHECK (callback_url IS NULL OR length(callback_url) <= 2048)
    NOT VALID;

COMMIT;
