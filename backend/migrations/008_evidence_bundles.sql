CREATE TABLE IF NOT EXISTS evidence_bundles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID,
    incident_id TEXT,
    namespace TEXT NOT NULL,
    cluster TEXT NOT NULL,
    bundle JSONB NOT NULL DEFAULT '{}',
    captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_bundles_finding ON evidence_bundles(finding_id);
CREATE INDEX IF NOT EXISTS idx_evidence_bundles_ns ON evidence_bundles(namespace, cluster);
CREATE INDEX IF NOT EXISTS idx_evidence_bundles_captured ON evidence_bundles(captured_at DESC);

ALTER TABLE inferences ADD COLUMN IF NOT EXISTS bundle_id UUID;
CREATE INDEX IF NOT EXISTS idx_inferences_bundle ON inferences(bundle_id);
