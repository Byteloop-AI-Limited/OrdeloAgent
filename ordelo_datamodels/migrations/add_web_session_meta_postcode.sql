-- ADR 0008 / plans/web-checkout-address-plan.md, step 1.
-- Run BEFORE deploying restaurant-frontend (step 2) and OrdeloAgent (step 3).
-- Additive and nullable: running code neither reads nor writes this column yet.
--
-- The full delivery postcode approved by eligibility when checkout starts
-- (e.g. 'SP1 2AB'). The backend uses it as the authority for the postcode
-- sector gate; the postcode sent with /web/address is no longer trusted.
-- web_order_request.address already holds the full postcode per order, so this
-- adds no new category of personal data (see plan section "Privacy").

select * from public.web_session_meta order by expires_at desc limit 5;
alter table public.web_session_meta
  add column if not exists postcode text;

-- Normalised UK postcode with one space, or NULL (collection, pre-migration rows).
-- NOT VALID: existing rows are not scanned; new and updated rows are checked.
alter table public.web_session_meta
  drop constraint if exists web_session_meta_postcode_format;
alter table public.web_session_meta
  add constraint web_session_meta_postcode_format
  check (postcode is null or postcode ~ '^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$') not valid;

comment on column public.web_session_meta.postcode is
  'Full delivery postcode approved at checkout start (ADR 0008). Authority for the postcode-sector gate in web_checkout.address().';

-- Rollback (only after reverting OrdeloAgent step 3, which fails closed without this column):
-- alter table public.web_session_meta drop constraint if exists web_session_meta_postcode_format;
-- alter table public.web_session_meta drop column if exists postcode;
select column_name, data_type, is_nullable from information_schema.columns
where table_name = 'web_session_meta' and column_name = 'postcode';
select conname from pg_constraint where conname = 'web_session_meta_postcode_format';

