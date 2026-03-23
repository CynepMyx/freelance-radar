CREATE TABLE IF NOT EXISTS projects (
    id            BIGINT PRIMARY KEY,
    source        TEXT NOT NULL DEFAULT 'kwork',
    title         TEXT NOT NULL,
    description   TEXT,
    price         INTEGER,
    price_max     INTEGER,
    category_id   INTEGER,
    parent_cat_id INTEGER,
    username      TEXT,
    hired_pct     INTEGER,
    offers        INTEGER,
    time_left     INTEGER,
    url           TEXT,
    seen_at       TIMESTAMPTZ DEFAULT NOW(),
    status        TEXT DEFAULT 'new',
    score         INTEGER,
    score_reason  TEXT
);
