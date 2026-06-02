CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    failure_class TEXT,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    signal_count INTEGER DEFAULT 0,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    rca_output TEXT,
    evidence JSONB DEFAULT '{}',
    classification JSONB,
    remediation_options JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_ns ON incidents(namespace, cluster_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status, severity);
