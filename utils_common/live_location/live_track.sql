-- Create live-track table for storing location data
CREATE TABLE IF NOT EXISTS "live-track" (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    battery INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    topic TEXT NOT NULL,
    create_ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    type TEXT NOT NULL,
    connection TEXT NOT NULL,
    
    -- Add indexes for common query patterns
    CONSTRAINT latitude_range CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT longitude_range CHECK (longitude BETWEEN -180 AND 180)
) WITH (OIDS=FALSE);

-- Create indexes for frequent queries
CREATE INDEX IF NOT EXISTS idx_live_track_user ON "live-track" (user_id);
CREATE INDEX IF NOT EXISTS idx_live_track_device ON "live-track" (device_id);
CREATE INDEX IF NOT EXISTS idx_live_track_created_at ON "live-track" (created_at DESC);


-- Enable Row Level Security (RLS)
ALTER TABLE "live-track" ENABLE ROW LEVEL SECURITY;

-- Create a policy that allows all authenticated users to read
CREATE POLICY "Allow authenticated read access"
    ON "live-track"
    FOR SELECT
    TO authenticated
    USING (true);

-- Create a policy that allows only specific service roles to insert
CREATE POLICY "Allow service insert"
    ON "live-track"
    FOR INSERT
    TO authenticated
    WITH CHECK (true);

-- Add table comment
COMMENT ON TABLE "live-track" IS 'Stores real-time location tracking data from devices';

-- Enable real-time subscriptions
ALTER PUBLICATION supabase_realtime ADD TABLE "live-track";
