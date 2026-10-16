CREATE TABLE IF NOT EXISTS public."live-track" (
    id uuid NOT NULL DEFAULT uuid_generate_v4(),
    battery integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    topic text NOT NULL,
    create_ts text NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    type text NOT NULL,
    connection text NOT NULL,
    CONSTRAINT "live-track_pkey" PRIMARY KEY (id),
    CONSTRAINT latitude_range CHECK (((latitude >= ('-90'::integer)::double precision) AND (latitude <= (90)::double precision))),
    CONSTRAINT longitude_range CHECK (((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision)))
);

CREATE INDEX IF NOT EXISTS idx_live_track_created_at ON public."live-track" USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_live_track_device ON public."live-track" USING btree (device_id);

CREATE INDEX IF NOT EXISTS idx_live_track_user ON public."live-track" USING btree (user_id);

DROP POLICY IF EXISTS "Allow authenticated read access" ON public."live-track";
CREATE POLICY "Allow authenticated read access" ON public."live-track"
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS "Allow service insert" ON public."live-track";
CREATE POLICY "Allow service insert" ON public."live-track"
    AS PERMISSIVE FOR INSERT TO authenticated
    WITH CHECK (true);
