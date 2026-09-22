-- HireFlow Phase 5 schema: evidence items, interview status, human decisions.

ALTER TABLE match_results
    ADD COLUMN IF NOT EXISTS status_after_interview TEXT;

CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    report_id TEXT NOT NULL REFERENCES reports (id) ON DELETE CASCADE,
    requirement_id TEXT NOT NULL REFERENCES requirements (id),
    source TEXT NOT NULL,
    quote TEXT NOT NULL,
    source_ref TEXT,
    interpretation TEXT NOT NULL DEFAULT '',
    strength TEXT NOT NULL,
    dimensions_supported JSONB NOT NULL DEFAULT '[]',
    contradicts_claim_id TEXT REFERENCES claims (id)
);

CREATE INDEX IF NOT EXISTS evidence_items_report_id_idx ON evidence_items (report_id);
CREATE INDEX IF NOT EXISTS evidence_items_candidate_id_idx ON evidence_items (candidate_id);
CREATE INDEX IF NOT EXISTS evidence_items_org_id_idx ON evidence_items (org_id);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    report_id TEXT NOT NULL REFERENCES reports (id) ON DELETE CASCADE,
    outcome TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL REFERENCES users (id),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS decisions_report_id_idx ON decisions (report_id);
CREATE INDEX IF NOT EXISTS decisions_org_id_idx ON decisions (org_id);

ALTER TABLE evidence_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
