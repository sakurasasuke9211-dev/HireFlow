-- HireFlow Phase 6 schema: File Assistant request audit log.

CREATE TABLE IF NOT EXISTS file_assistant_requests (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    user_id TEXT NOT NULL REFERENCES users (id),
    query TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    primary_locator TEXT,
    hit_locators JSONB NOT NULL DEFAULT '[]',
    warnings JSONB NOT NULL DEFAULT '[]',
    answer TEXT,
    parsed JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS file_assistant_requests_org_id_idx ON file_assistant_requests (org_id);
CREATE INDEX IF NOT EXISTS file_assistant_requests_user_id_idx ON file_assistant_requests (user_id);
CREATE INDEX IF NOT EXISTS file_assistant_requests_created_at_idx ON file_assistant_requests (created_at DESC);

ALTER TABLE file_assistant_requests ENABLE ROW LEVEL SECURITY;
