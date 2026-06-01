-- Per-cluster adaptive profiles
CREATE TABLE IF NOT EXISTS cluster_profiles (
    cluster_id TEXT PRIMARY KEY,
    profile_data JSONB NOT NULL DEFAULT '{}',
    confidence FLOAT DEFAULT 0.0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tuning proposals (suggest + approve pattern)
CREATE TABLE IF NOT EXISTS tuning_proposals (
    id SERIAL PRIMARY KEY,
    proposal_id TEXT UNIQUE NOT NULL,
    cluster_id TEXT NOT NULL,
    category TEXT NOT NULL,
    current_value JSONB,
    proposed_value JSONB,
    evidence JSONB,
    impact_estimate TEXT,
    confidence FLOAT DEFAULT 0.0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON tuning_proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_cluster ON tuning_proposals(cluster_id);

INSERT INTO applied_migrations (filename) VALUES ('003_cluster_profiles.sql') ON CONFLICT DO NOTHING;
