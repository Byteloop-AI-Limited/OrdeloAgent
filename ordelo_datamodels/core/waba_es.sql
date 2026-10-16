CREATE TABLE IF NOT EXISTS waba_es (
  id               BIGSERIAL PRIMARY KEY,
  phone_num        TEXT,          -- display phone number as string
  business_ref     TEXT,          -- business reference[]
  waba_id          BIGINT,
  phone_number_id  BIGINT,
  business_id      BIGINT,
  event_type       TEXT,          -- e.g., WA_EMBEDDED_SIGNUP, FB_AUTH_RESPONSE (value comes from event payload)
  code             TEXT,          -- FB auth code
  business_token   TEXT,          -- Sensitive: consider encrypting or restricting access
  dt DATE NOT NULL DEFAULT CURRENT_DATE,
  dtts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Backward-compatible migration for existing deployments
-- ALTER TABLE IF EXISTS waba_es
--   ADD COLUMN IF NOT EXISTS phone_num TEXT;

select * from waba_es order by dtts desc;

update waba_es set business_ref='sfcs' where id = 5;
-- drop table waba_es;