CREATE TABLE IF NOT EXISTS rubric_evaluations (
    id SERIAL PRIMARY KEY,
    cluster_id TEXT NOT NULL,
    overall_score TEXT NOT NULL,
    rubric_scores JSONB NOT NULL,
    source TEXT DEFAULT 'manual',
    source_id TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rubric_eval_cluster
    ON rubric_evaluations(cluster_id, created_at DESC);
