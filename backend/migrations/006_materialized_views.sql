-- Materialized view tables for dashboard performance
-- Refresh is managed by the writer thread in app/db.py

CREATE TABLE IF NOT EXISTS mv_metrics_funnel (
    id SERIAL PRIMARY KEY,
    window_label TEXT NOT NULL,
    total_signals BIGINT DEFAULT 0,
    high_severity BIGINT DEFAULT 0,
    medium_severity BIGINT DEFAULT 0,
    total_decisions BIGINT DEFAULT 0,
    total_findings BIGINT DEFAULT 0,
    total_inferences BIGINT DEFAULT 0,
    compression_ratio FLOAT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mv_inference_model_stats (
    id SERIAL PRIMARY KEY,
    model TEXT NOT NULL,
    tier TEXT,
    total_calls BIGINT DEFAULT 0,
    avg_latency_ms FLOAT DEFAULT 0,
    avg_tokens_out FLOAT DEFAULT 0,
    error_count BIGINT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_metrics_window ON mv_metrics_funnel(window_label);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_inference_model ON mv_inference_model_stats(model);
