-- HireFlow Phase 2 schema: match results and gaps.

CREATE TABLE IF NOT EXISTS match_results (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    requirement_id TEXT NOT NULL REFERENCES requirements (id),
    status TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    rationale TEXT NOT NULL,
    dimension_flags JSONB NOT NULL DEFAULT '{}',
    supporting_claim_ids JSONB NOT NULL DEFAULT '[]',
    run_id TEXT NOT NULL REFERENCES pipeline_runs (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS match_results_job_id_idx ON match_results (job_id);
CREATE INDEX IF NOT EXISTS match_results_candidate_id_idx ON match_results (candidate_id);
CREATE UNIQUE INDEX IF NOT EXISTS match_results_candidate_requirement_idx
    ON match_results (candidate_id, requirement_id);

CREATE TABLE IF NOT EXISTS gaps (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    match_result_id TEXT NOT NULL REFERENCES match_results (id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    investigation_goal TEXT NOT NULL,
    suggested_probe_themes JSONB NOT NULL DEFAULT '[]',
    deal_breaker BOOLEAN NOT NULL DEFAULT FALSE,
    skip_probe BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS gaps_match_result_id_idx ON gaps (match_result_id);

ALTER TABLE match_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE gaps ENABLE ROW LEVEL SECURITY;
