CREATE TABLE webpush_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT UNIQUE,
    p256dh_key TEXT,
    auth_key TEXT,
    maker_filter TEXT,
    item_filter TEXT,
    event_type_filter TEXT,
    created_at TEXT,
    last_used_at TEXT,
    is_active INTEGER DEFAULT 1
);
CREATE TABLE webpush_delivery_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER,
    endpoint TEXT,
    status TEXT,
    event_type TEXT,
    product_id TEXT,
    sent_at TEXT,
    detail TEXT
);
