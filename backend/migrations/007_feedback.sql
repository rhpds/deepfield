CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    incident_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_index INTEGER DEFAULT 0,
    rating TEXT NOT NULL,
    comment TEXT DEFAULT '',
    model TEXT DEFAULT '',
    task_type TEXT DEFAULT '',
    user_id TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_incident ON feedback(incident_id);
CREATE INDEX IF NOT EXISTS idx_feedback_model ON feedback(model, task_type);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
