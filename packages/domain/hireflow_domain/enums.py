from enum import StrEnum


class UserRole(StrEnum):
    recruiter = "recruiter"


class JobStatus(StrEnum):
    draft = "draft"
    active = "active"
    closed = "closed"


class DocumentOwnerType(StrEnum):
    job = "job"
    candidate = "candidate"
    transcript = "transcript"


class DocumentKind(StrEnum):
    jd = "jd"
    resume = "resume"
    transcript = "transcript"


class FileKind(StrEnum):
    jd = "jd"
    resume = "resume"
    transcript = "transcript"
    screening_brief = "screening_brief"
    interview_brief = "interview_brief"
    evidence = "evidence"


class FileAction(StrEnum):
    locate = "locate"
    download = "download"
    read = "read"
    summarize = "summarize"
    parse = "parse"


class PipelineGraph(StrEnum):
    extract = "extract"
    screening = "screening"
    transcript = "transcript"
    report = "report"


class PipelineStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class RequirementPriority(StrEnum):
    must_have = "must_have"
    nice_to_have = "nice_to_have"
    unclear_priority = "unclear_priority"


class RequirementCategory(StrEnum):
    skill = "skill"
    experience = "experience"
    education = "education"
    domain = "domain"
    tooling = "tooling"
    soft_skill = "soft_skill"
    other = "other"


class ClaimKind(StrEnum):
    skill = "skill"
    implied_skill = "implied_skill"
    years_claim = "years_claim"
    project = "project"
    education = "education"
    other = "other"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    MISSING = "MISSING"
    UNCLEAR = "UNCLEAR"


class OverallMatch(StrEnum):
    poor = "poor"
    average = "average"
    good = "good"
    perfect = "perfect"


class GapSeverity(StrEnum):
    blocker = "blocker"
    high = "high"
    medium = "medium"
    low = "low"


class InterviewPlanStatus(StrEnum):
    draft = "draft"
    approved = "approved"
    superseded = "superseded"


class QuestionSource(StrEnum):
    generated = "generated"
    recruiter_edited = "recruiter_edited"


class ReportKind(StrEnum):
    interview_brief = "interview_brief"
    evidence = "evidence"


class EvidenceDimension(StrEnum):
    named = "named"
    applied = "applied"
    complexity = "complexity"
    professional = "professional"
    ownership = "ownership"
    outcome = "outcome"


class TranscriptSource(StrEnum):
    file = "file"
    paste = "paste"


class TranscriptStatus(StrEnum):
    uploaded = "uploaded"
    parsed = "parsed"
    analyzed = "analyzed"
    failed = "failed"


class Speaker(StrEnum):
    recruiter = "recruiter"
    candidate = "candidate"
    unknown = "unknown"


class ProbeVerdict(StrEnum):
    sufficient = "sufficient"
    shallow = "shallow"
    not_discussed = "not_discussed"
    confirmed_missing = "confirmed_missing"
    contradiction = "contradiction"


class EvidenceSource(StrEnum):
    resume = "resume"
    interview = "interview"


class EvidenceStrength(StrEnum):
    strong = "strong"
    weak = "weak"
    none = "none"


class DecisionOutcome(StrEnum):
    advance = "advance"
    hold = "hold"
    reject = "reject"
