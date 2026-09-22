from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RowModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Org(RowModel):
    id: str
    name: str
    created_at: datetime


class User(RowModel):
    id: str
    org_id: str
    email: str
    name: str
    password_hash: str
    role: str = "recruiter"
    created_at: datetime


class Job(RowModel):
    id: str
    org_id: str
    title: str
    status: str = "draft"
    created_by: str
    created_at: datetime


class Candidate(RowModel):
    id: str
    org_id: str
    job_id: str
    full_name: str
    email: str | None = None
    created_at: datetime


class Document(RowModel):
    id: str
    org_id: str
    owner_type: str
    owner_id: str
    kind: str
    storage_key: str
    original_filename: str
    mime: str
    sha256: str
    extracted_text: str | None = None
    version: int = 1
    uploaded_by: str
    created_at: datetime


class Requirement(RowModel):
    id: str
    org_id: str
    job_id: str
    document_version: int
    text: str
    normalized_label: str
    category: str
    priority: str
    source_quote: str
    source_span: dict[str, Any] | None = None
    recruiter_edited: bool = False
    sort_order: int = 0


class Profile(RowModel):
    id: str
    org_id: str
    candidate_id: str
    full_name: str | None = None
    email: str | None = None
    summary: str | None = None
    years_experience: float | None = None
    education: list[Any] | None = None
    roles: list[Any] | None = None
    skills_listed: list[Any] | None = None
    parser_warnings: list[Any] | None = None


class Claim(RowModel):
    id: str
    org_id: str
    candidate_id: str
    kind: str
    text: str
    skill_label: str | None = None
    years: float | None = None
    source_span: dict[str, Any] | None = None
    quote: str


class PipelineRun(RowModel):
    id: str
    org_id: str
    graph: str
    subject_type: str
    subject_id: str
    status: str
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AgentTrace(RowModel):
    id: str
    org_id: str
    run_id: str
    agent: str
    schema_version: str = "1.0"
    model: str | None = None
    prompt_version: str | None = None
    input_hash: str | None = None
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None
    latency_ms: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


class MatchResult(RowModel):
    id: str
    org_id: str
    job_id: str
    candidate_id: str
    requirement_id: str
    status: str
    confidence: float | None = None
    rationale: str
    dimension_flags: dict[str, Any] | None = None
    supporting_claim_ids: list[str] | None = None
    run_id: str
    status_after_interview: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Gap(RowModel):
    id: str
    org_id: str
    match_result_id: str
    severity: str
    investigation_goal: str
    suggested_probe_themes: list[str] | None = None
    deal_breaker: bool = False
    skip_probe: bool = False


class InterviewPlan(RowModel):
    id: str
    org_id: str
    candidate_id: str
    job_id: str
    status: str = "draft"
    version: int = 1
    brief_report_id: str | None = None
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class PlannedQuestion(RowModel):
    id: str
    org_id: str
    plan_id: str
    requirement_id: str
    sort_order: int = 0
    prompt: str
    planned_followups: list[str] | None = None
    evidence_target: list[str] | None = None
    source: str = "generated"
    dropped: bool = False


class Report(RowModel):
    id: str
    org_id: str
    candidate_id: str
    job_id: str
    plan_id: str | None = None
    kind: str
    version: int = 1
    storage_key: str
    original_filename: str
    mime: str = "text/markdown"
    body: dict[str, Any] | None = None
    generated_from_run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Transcript(RowModel):
    id: str
    org_id: str
    candidate_id: str
    job_id: str
    plan_id: str | None = None
    document_id: str | None = None
    source: str
    status: str = "uploaded"
    version: int = 1
    warnings: list[Any] | None = None
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class TranscriptTurn(RowModel):
    id: str
    org_id: str
    transcript_id: str
    speaker: str
    text: str
    char_start: int | None = None
    char_end: int | None = None
    requirement_id: str | None = None
    question_id: str | None = None
    sort_order: int = 0
    recruiter_edited: bool = False


class ProbeResult(RowModel):
    id: str
    org_id: str
    transcript_id: str
    requirement_id: str
    verdict: str
    missing_dimensions: list[str] | None = None
    supporting_turn_ids: list[str] | None = None
    remaining_followups: list[str] | None = None
    rationale: str


class EvidenceItem(RowModel):
    id: str
    org_id: str
    candidate_id: str
    report_id: str
    requirement_id: str
    source: str
    quote: str
    source_ref: str | None = None
    interpretation: str = ""
    strength: str
    dimensions_supported: list[str] | None = None
    contradicts_claim_id: str | None = None


class Decision(RowModel):
    id: str
    org_id: str
    report_id: str
    outcome: str
    notes: str = ""
    decided_by: str
    decided_at: datetime = Field(default_factory=utcnow)


class FileAssistantRequest(RowModel):
    id: str
    org_id: str
    user_id: str
    query: str
    action: str
    summary: str = ""
    primary_locator: str | None = None
    hit_locators: list[Any] | None = None
    warnings: list[Any] | None = None
    answer: str | None = None
    parsed: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
