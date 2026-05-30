-- Agent stats snapshots for persistence across restarts
CREATE TABLE IF NOT EXISTS agent_stats_snapshots (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    agent_name TEXT NOT NULL,
    total_evaluated INT DEFAULT 0,
    escalated INT DEFAULT 0,
    kept INT DEFAULT 0,
    dropped INT DEFAULT 0,
    suppressed INT DEFAULT 0,
    deduped INT DEFAULT 0,
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_stats_captured ON agent_stats_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_agent_stats_name ON agent_stats_snapshots(agent_name, captured_at);

-- Session-level snapshots for metrics persistence
CREATE TABLE IF NOT EXISTS session_snapshots (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    raw_signals INT DEFAULT 0,
    reasoning_tasks INT DEFAULT 0,
    inference_calls INT DEFAULT 0,
    findings INT DEFAULT 0,
    dropped INT DEFAULT 0,
    compression_ratio FLOAT DEFAULT 0,
    signals_per_second FLOAT DEFAULT 0,
    projected_clusters INT DEFAULT 0,
    model_stats JSONB DEFAULT '{}',
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_snap_captured ON session_snapshots(captured_at);

-- Time-series metrics for historical charts
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id SERIAL PRIMARY KEY,
    session_id TEXT,
    signals_per_second FLOAT,
    compression_ratio FLOAT,
    reasoning_tasks INT,
    projected_clusters INT,
    avg_latency_ms FLOAT,
    avg_tps FLOAT,
    inference_in_flight INT,
    cluster_state JSONB DEFAULT '{}',
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metrics_snap_captured ON metrics_snapshots(captured_at);

INSERT INTO applied_migrations (filename) VALUES ('002_stats_persistence.sql') ON CONFLICT DO NOTHING;
