CREATE TABLE price_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    priority INTEGER,
    product_id TEXT,
    store TEXT,
    price INTEGER,
    url TEXT,
    previous_price INTEGER,
    reference_price INTEGER,
    change_percent REAL,
    period_days INTEGER,
    color_key TEXT,
    recorded_at TEXT,
    suppressed INTEGER DEFAULT 0,
    superseded_by INTEGER,
    twitter_posted INTEGER DEFAULT 0,
    twitter_enabled INTEGER DEFAULT 1
);
