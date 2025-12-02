CREATE TABLE IF NOT EXISTS debug_log (
    id SERIAL PRIMARY KEY,
    trigger_name TEXT,
    order_number TEXT,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);