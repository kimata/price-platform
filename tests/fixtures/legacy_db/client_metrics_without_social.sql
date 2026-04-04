CREATE TABLE client_perf_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    device_type TEXT NOT NULL,
    ttfb_ms REAL,
    dom_interactive_ms REAL,
    dom_complete_ms REAL,
    load_event_ms REAL,
    page_path TEXT,
    user_agent TEXT
);

CREATE TABLE client_perf_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    device_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    min_value REAL NOT NULL,
    q1_value REAL NOT NULL,
    median_value REAL NOT NULL,
    q3_value REAL NOT NULL,
    max_value REAL NOT NULL,
    avg_value REAL NOT NULL,
    entry_count INTEGER NOT NULL,
    UNIQUE(date, device_type, metric_name)
);

CREATE TABLE web_vitals_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    device_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    rating TEXT NOT NULL,
    page_path TEXT
);

CREATE TABLE web_vitals_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    device_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    min_value REAL NOT NULL,
    q1_value REAL NOT NULL,
    median_value REAL NOT NULL,
    q3_value REAL NOT NULL,
    max_value REAL NOT NULL,
    avg_value REAL NOT NULL,
    entry_count INTEGER NOT NULL,
    good_count INTEGER NOT NULL DEFAULT 0,
    needs_improvement_count INTEGER NOT NULL DEFAULT 0,
    poor_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(date, device_type, metric_name)
);
