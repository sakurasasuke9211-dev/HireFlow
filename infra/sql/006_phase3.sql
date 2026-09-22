-- HireFlow Phase 3 schema: interview plans, planned questions, report files.

CREATE TABLE IF NOT EXISTS interview_plans (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    brief_report_id TEXT,
    run_id TEXT REFERENCES pipeline_runs (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS interview_plans_candidate_id_idx ON interview_plans (candidate_id);
CREATE INDEX IF NOT EXISTS interview_plans_org_id_idx ON interview_plans (org_id);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    plan_id TEXT REFERENCES interview_plans (id),
    kind TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    storage_key TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'text/markdown',
    body JSONB NOT NULL DEFAULT '{}',
    generated_from_run_id TEXT REFERENCES pipeline_runs (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reports_candidate_id_idx ON reports (candidate_id);
CREATE INDEX IF NOT EXISTS reports_plan_id_idx ON reports (plan_id);
CREATE INDEX IF NOT EXISTS reports_org_id_idx ON reports (org_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'interview_plans_brief_report_id_fkey'
    ) THEN
        ALTER TABLE interview_plans
            ADD CONSTRAINT interview_plans_brief_report_id_fkey
            FOREIGN KEY (brief_report_id) REFERENCES reports (id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS planned_questions (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    plan_id TEXT NOT NULL REFERENCES interview_plans (id) ON DELETE CASCADE,
    requirement_id TEXT NOT NULL REFERENCES requirements (id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    planned_followups JSONB NOT NULL DEFAULT '[]',
    evidence_target JSONB NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'generated',
    dropped BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS planned_questions_plan_id_idx ON planned_questions (plan_id);

ALTER TABLE interview_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE planned_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
