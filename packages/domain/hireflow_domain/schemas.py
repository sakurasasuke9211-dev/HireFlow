from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hireflow_domain.enums import (
    ClaimKind,
    DecisionOutcome,
    DocumentKind,
    DocumentOwnerType,
    EvidenceDimension,
    EvidenceSource,
    EvidenceStrength,
    FileAction,
    FileKind,
    GapSeverity,
    InterviewPlanStatus,
    JobStatus,
    MatchStatus,
    OverallMatch,
    PipelineGraph,
    PipelineStatus,
    ProbeVerdict,
    QuestionSource,
    ReportKind,
    RequirementCategory,
    RequirementPriority,
    Speaker,
    TranscriptSource,
    TranscriptStatus,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserPublic(ORMModel):
    id: str
    org_id: str
    email: str
    name: str
    role: UserRole


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: str
    org_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PipelineRunPublic(ORMModel):
    id: str
    graph: PipelineGraph
    subject_type: str
    subject_id: str
    status: PipelineStatus
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class DocumentPublic(ORMModel):
    id: str
    owner_type: DocumentOwnerType
    owner_id: str
    kind: DocumentKind
    original_filename: str
    mime: str
    sha256: str
    extracted_text: str | None = None
    version: int
    created_at: datetime
    extract_run: PipelineRunPublic | None = None


class JobSummary(ORMModel):
    id: str
    title: str
    status: JobStatus
    created_at: datetime
    candidate_count: int = 0
    has_jd: bool = False


class SourceSpan(BaseModel):
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = ""


class RequirementPublic(ORMModel):
    id: str
    job_id: str
    document_version: int
    text: str
    normalized_label: str
    category: RequirementCategory
    priority: RequirementPriority
    source_quote: str
    source_span: SourceSpan | None = None
    recruiter_edited: bool
    sort_order: int


class RequirementPatch(BaseModel):
    text: str | None = None
    normalized_label: str | None = None
    category: RequirementCategory | None = None
    priority: RequirementPriority | None = None
    sort_order: int | None = None
    dropped: bool = False


class ClaimPublic(ORMModel):
    id: str
    candidate_id: str
    kind: ClaimKind
    text: str
    skill_label: str | None = None
    years: float | None = None
    source_span: SourceSpan | None = None
    quote: str


class ProfilePublic(ORMModel):
    id: str
    candidate_id: str
    full_name: str | None = None
    email: str | None = None
    summary: str | None = None
    years_experience: float | None = None
    education: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    skills_listed: list[str] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)


class CandidatePublic(ORMModel):
    id: str
    job_id: str
    full_name: str
    email: str | None = None
    created_at: datetime
    resume: DocumentPublic | None = None
    profile: ProfilePublic | None = None
    claims: list[ClaimPublic] = Field(default_factory=list)
    parse_run: PipelineRunPublic | None = None
    match_run: PipelineRunPublic | None = None
    overall_match: OverallMatch | None = None


class JobDetail(ORMModel):
    id: str
    title: str
    status: JobStatus
    created_at: datetime
    jd: DocumentPublic | None = None
    candidates: list[CandidatePublic] = Field(default_factory=list)
    requirements: list[RequirementPublic] = Field(default_factory=list)
    parse_run: PipelineRunPublic | None = None


class UploadResult(BaseModel):
    document: DocumentPublic
    run: PipelineRunPublic
    reused: bool = False


class DimensionFlags(BaseModel):
    named: int = 0
    applied: int = 0
    complexity: int = 0
    professional: int = 0
    ownership: int = 0
    outcome: int = 0


class MatchResultPublic(ORMModel):
    id: str
    job_id: str
    candidate_id: str
    requirement_id: str
    status: MatchStatus
    confidence: float | None = None
    rationale: str
    dimension_flags: DimensionFlags
    supporting_claim_ids: list[str] = Field(default_factory=list)
    run_id: str
    requirement_label: str = ""
    requirement_priority: RequirementPriority | None = None
    quotes: list[str] = Field(default_factory=list)
    status_after_interview: MatchStatus | None = None


class GapPublic(ORMModel):
    id: str
    match_result_id: str
    requirement_id: str
    requirement_label: str = ""
    status: MatchStatus | None = None
    severity: GapSeverity
    investigation_goal: str
    suggested_probe_themes: list[str] = Field(default_factory=list)
    deal_breaker: bool = False
    skip_probe: bool = False


class GapPatch(BaseModel):
    deal_breaker: bool | None = None
    skip_probe: bool | None = None


class MatrixCell(BaseModel):
    candidate_id: str
    requirement_id: str
    status: MatchStatus | None = None
    rationale: str | None = None
    quotes: list[str] = Field(default_factory=list)


class MatrixCandidate(BaseModel):
    id: str
    full_name: str
    overall_match: OverallMatch | None = None


class MatrixResponse(BaseModel):
    job_id: str
    requirements: list[RequirementPublic]
    candidates: list[MatrixCandidate]
    cells: list[MatrixCell]


class ScreenStatus(BaseModel):
    step: str
    message: str
    run: PipelineRunPublic | None = None


class PlannedQuestionPublic(ORMModel):
    id: str
    plan_id: str
    requirement_id: str
    requirement_label: str = ""
    match_status: MatchStatus | None = None
    sort_order: int = 0
    prompt: str
    planned_followups: list[str] = Field(default_factory=list)
    evidence_target: list[EvidenceDimension] = Field(default_factory=list)
    source: QuestionSource
    dropped: bool = False


class PlannedQuestionPatch(BaseModel):
    prompt: str | None = None
    planned_followups: list[str] | None = None
    sort_order: int | None = None
    dropped: bool | None = None


class ReportPublic(ORMModel):
    id: str
    candidate_id: str
    job_id: str
    plan_id: str | None = None
    kind: ReportKind
    version: int
    original_filename: str
    mime: str
    created_at: datetime


class InterviewPlanPublic(ORMModel):
    id: str
    candidate_id: str
    job_id: str
    status: InterviewPlanStatus
    version: int
    brief_report: ReportPublic | None = None
    questions: list[PlannedQuestionPublic] = Field(default_factory=list)
    run: PipelineRunPublic | None = None
    created_at: datetime


class InterviewPlanResponse(BaseModel):
    plan: InterviewPlanPublic | None = None
    run: PipelineRunPublic | None = None


class TranscriptTurnPublic(ORMModel):
    id: str
    speaker: Speaker
    text: str
    char_start: int | None = None
    char_end: int | None = None
    requirement_id: str | None = None
    requirement_label: str = ""
    question_id: str | None = None
    sort_order: int = 0
    recruiter_edited: bool = False


class TranscriptTurnPatch(BaseModel):
    speaker: Speaker | None = None
    requirement_id: str | None = None
    question_id: str | None = None


class ProbeResultPublic(ORMModel):
    id: str
    requirement_id: str
    requirement_label: str = ""
    verdict: ProbeVerdict
    missing_dimensions: list[EvidenceDimension] = Field(default_factory=list)
    supporting_turn_ids: list[str] = Field(default_factory=list)
    remaining_followups: list[str] = Field(default_factory=list)
    rationale: str


class TranscriptPublic(ORMModel):
    id: str
    candidate_id: str
    job_id: str
    plan_id: str | None = None
    source: TranscriptSource
    status: TranscriptStatus
    version: int
    warnings: list[str] = Field(default_factory=list)
    original_filename: str | None = None
    created_at: datetime
    run: PipelineRunPublic | None = None


class TranscriptDetail(TranscriptPublic):
    extracted_text: str | None = None
    turns: list[TranscriptTurnPublic] = Field(default_factory=list)
    probes: list[ProbeResultPublic] = Field(default_factory=list)


class DecisionCreate(BaseModel):
    outcome: DecisionOutcome
    notes: str = ""


class DecisionPublic(ORMModel):
    id: str
    report_id: str
    outcome: DecisionOutcome
    notes: str = ""
    decided_by: str
    decided_at: datetime


class EvidenceItemPublic(ORMModel):
    id: str
    code: str
    requirement_id: str
    requirement_label: str = ""
    source: EvidenceSource
    quote: str
    interpretation: str = ""
    strength: EvidenceStrength
    dimensions_supported: list[EvidenceDimension] = Field(default_factory=list)
    contradicts: bool = False


class RequirementAssessment(BaseModel):
    requirement_id: str
    requirement_label: str
    priority: RequirementPriority
    status_after_resume: MatchStatus
    status_after_interview: MatchStatus | None = None
    final: MatchStatus
    unvalidated: bool = False
    strongest_quote: str = ""
    source: EvidenceSource | None = None
    remaining_doubt: str = ""
    evidence_codes: list[str] = Field(default_factory=list)


class UnresolvedGap(BaseModel):
    requirement_id: str
    requirement_label: str
    verdict: ProbeVerdict | None = None
    followups: list[str] = Field(default_factory=list)
    note: str = ""


class CoverageRow(BaseModel):
    requirement_id: str
    requirement_label: str
    verdict: ProbeVerdict | None = None
    skipped_in_plan: bool = False


class ContradictionRow(BaseModel):
    requirement_label: str
    quote: str
    interpretation: str = ""
    evidence_code: str = ""


class EvidenceReportBody(BaseModel):
    partial: bool = False
    headline: str = ""
    generated_at: str = ""
    transcript_id: str | None = None
    transcript_version: int | None = None
    overall_after_resume: OverallMatch | None = None
    overall_after_interview: OverallMatch | None = None
    matrix: list[RequirementAssessment] = Field(default_factory=list)
    must_haves: list[RequirementAssessment] = Field(default_factory=list)
    unresolved: list[UnresolvedGap] = Field(default_factory=list)
    contradictions: list[ContradictionRow] = Field(default_factory=list)
    coverage: list[CoverageRow] = Field(default_factory=list)
    remaining_risks: list[str] = Field(default_factory=list)
    closing: str = "HireFlow does not hire; the recruiter decides."
    evidence: list[EvidenceItemPublic] = Field(default_factory=list)


class EvidenceReportResponse(BaseModel):
    report: ReportPublic | None = None
    body: EvidenceReportBody | None = None
    decision: DecisionPublic | None = None
    run: PipelineRunPublic | None = None


class FileAssistantChatContext(BaseModel):
    primary_locator: str | None = None
    candidate_name: str | None = None
    job_title: str | None = None
    kind: FileKind | None = None


class FileAssistantPageContext(BaseModel):
    candidate_id: str | None = None
    candidate_name: str | None = None
    job_id: str | None = None
    job_title: str | None = None


class FileAssistantChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)
    context: FileAssistantChatContext | None = None


class FileAssistantChatRequest(BaseModel):
    messages: list[FileAssistantChatTurn] = Field(min_length=1, max_length=24)
    page_context: FileAssistantPageContext | None = None


class FileLocatorQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class FileHitPublic(BaseModel):
    locator: str
    kind: FileKind
    label: str
    filename: str
    job_title: str
    candidate_name: str | None = None
    download_path: str
    available: bool = True
    reason: str = ""


class FileLocatorResponse(BaseModel):
    query: str
    summary: str
    action: FileAction = FileAction.locate
    want_download: bool = False
    warnings: list[str] = Field(default_factory=list)
    hits: list[FileHitPublic] = Field(default_factory=list)
    primary_locator: str | None = None
    answer: str | None = None
    parsed: dict | None = None
    request_id: str | None = None
    reply: str | None = None
    context: FileAssistantChatContext | None = None


class FileAssistantChatResponse(FileLocatorResponse):
    reply: str


class FileAssistantHistoryItem(ORMModel):
    id: str
    query: str
    action: FileAction
    summary: str
    primary_locator: str | None = None
    created_at: datetime
