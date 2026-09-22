-- HireFlow Phase 4 schema: transcripts, turns, and probe results.

CREATE TABLE IF NOT EXISTS transcripts (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    candidate_id TEXT NOT NULL REFERENCES candidates (id),
    job_id TEXT NOT NULL REFERENCES jobs (id),
    plan_id TEXT REFERENCES interview_plans (id),
    document_id TEXT REFERENCES documents (id),
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    version INTEGER NOT NULL DEFAULT 1,
    warnings JSONB NOT NULL DEFAULT '[]',
    run_id TEXT REFERENCES pipeline_runs (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS transcripts_candidate_id_idx ON transcripts (candidate_id);
CREATE INDEX IF NOT EXISTS transcripts_org_id_idx ON transcripts (org_id);
CREATE INDEX IF NOT EXISTS transcripts_document_id_idx ON transcripts (document_id);

CREATE TABLE IF NOT EXISTS transcript_turns (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    transcript_id TEXT NOT NULL REFERENCES transcripts (id) ON DELETE CASCADE,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    requirement_id TEXT REFERENCES requirements (id),
    question_id TEXT REFERENCES planned_questions (id),
    sort_order INTEGER NOT NULL DEFAULT 0,
    recruiter_edited BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS transcript_turns_transcript_id_idx ON transcript_turns (transcript_id);

CREATE TABLE IF NOT EXISTS probe_results (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs (id),
    transcript_id TEXT NOT NULL REFERENCES transcripts (id) ON DELETE CASCADE,
    requirement_id TEXT NOT NULL REFERENCES requirements (id),
    verdict TEXT NOT NULL,
    missing_dimensions JSONB NOT NULL DEFAULT '[]',
    supporting_turn_ids JSONB NOT NULL DEFAULT '[]',
    remaining_followups JSONB NOT NULL DEFAULT '[]',
    rationale TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS probe_results_transcript_requirement_idx
    ON probe_results (transcript_id, requirement_id);
CREATE INDEX IF NOT EXISTS probe_results_transcript_id_idx ON probe_results (transcript_id);

ALTER TABLE transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE probe_results ENABLE ROW LEVEL SECURITY;
