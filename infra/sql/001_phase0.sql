-- HireFlow Phase 0 schema for the Supabase project.
-- Apply in the SQL editor, or set SUPABASE_DB_URL and start the API.

CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'recruiter',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS users_org_id_idx ON users (org_id);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS jobs_org_id_idx ON jobs (org_id);

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    full_name TEXT NOT NULL,
    email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS candidates_job_id_idx ON candidates (job_id);
CREATE INDEX IF NOT EXISTS candidates_org_id_idx ON candidates (org_id);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    extracted_text TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    uploaded_by TEXT NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS documents_owner_idx ON documents (owner_type, owner_id);
CREATE INDEX IF NOT EXISTS documents_sha256_idx ON documents (org_id, sha256);
CREATE INDEX IF NOT EXISTS documents_org_id_idx ON documents (org_id);
CREATE UNIQUE INDEX IF NOT EXISTS documents_dedup_idx
    ON documents (org_id, sha256, owner_type, owner_id, kind);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    graph TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS pipeline_runs_subject_idx ON pipeline_runs (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS pipeline_runs_org_id_idx ON pipeline_runs (org_id);

CREATE TABLE IF NOT EXISTS agent_traces (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    run_id TEXT NOT NULL REFERENCES pipeline_runs (id),
    agent TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    model TEXT,
    prompt_version TEXT,
    input_hash TEXT,
    input_json JSONB,
    output_json JSONB,
    token_usage JSONB,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS agent_traces_run_id_idx ON agent_traces (run_id);
