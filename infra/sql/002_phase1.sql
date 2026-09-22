-- HireFlow Phase 1 schema for the Supabase project.

CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    document_version INTEGER NOT NULL,
    text TEXT NOT NULL,
    normalized_label TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    source_quote TEXT NOT NULL,
    source_span JSONB,
    recruiter_edited BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS requirements_job_id_idx ON requirements (job_id);
CREATE INDEX IF NOT EXISTS requirements_org_id_idx ON requirements (org_id);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates (id),
    full_name TEXT,
    email TEXT,
    summary TEXT,
    years_experience DOUBLE PRECISION,
    education JSONB,
    roles JSONB,
    skills_listed JSONB,
    parser_warnings JSONB
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    skill_label TEXT,
    years DOUBLE PRECISION,
    source_span JSONB,
    quote TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS claims_candidate_id_idx ON claims (candidate_id);
CREATE INDEX IF NOT EXISTS claims_org_id_idx ON claims (org_id);
