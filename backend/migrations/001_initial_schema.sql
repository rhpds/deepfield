-- DeepField persistence schema
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster TEXT NOT NULL,
    namespace TEXT NOT NULL,
    resource_kind TEXT,
    resource_name TEXT,
    signal_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    raw_payload JSONB,
    evidence JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_cluster_ts ON signals(cluster, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_severity ON signals(severity, created_at DESC);

CREATE TABLE IF NOT EXISTS findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    summary TEXT,
    namespaces TEXT[],
    clusters TEXT[],
    signal_count INT,
    evidence JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID REFERENCES findings(id) ON DELETE SET NULL,
    model TEXT NOT NULL,
    hardware_lane TEXT,
    task_type TEXT NOT NULL,
    severity TEXT,
    prompt TEXT,
    output TEXT,
    tokens_in INT DEFAULT 0,
    tokens_out INT DEFAULT 0,
    latency_ms FLOAT DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inferences_model ON inferences(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inferences_task ON inferences(task_type, created_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filter_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT,
    signal_id TEXT,
    evidence JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decisions_filter ON decisions(filter_name, created_at DESC);

CREATE TABLE IF NOT EXISTS remediations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inference_id UUID REFERENCES inferences(id) ON DELETE SET NULL,
    cluster TEXT NOT NULL,
    namespace TEXT NOT NULL,
    command TEXT NOT NULL,
    resource_kind TEXT,
    resource_name TEXT,
    status TEXT NOT NULL,
    output TEXT,
    executed_by TEXT DEFAULT 'deepfield',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT now(),
    stopped_at TIMESTAMPTZ,
    total_signals INT DEFAULT 0,
    total_findings INT DEFAULT 0,
    total_inferences INT DEFAULT 0,
    compression_ratio FLOAT DEFAULT 0,
    metrics_summary JSONB
);

CREATE TABLE IF NOT EXISTS applied_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
);
INSERT INTO applied_migrations (filename) VALUES ('001_initial_schema.sql') ON CONFLICT DO NOTHING;
