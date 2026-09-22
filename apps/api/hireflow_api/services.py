from __future__ import annotations

import asyncio
import hashlib
import re
import uuid

from hireflow_agents.interview_designer import default_followups
from hireflow_agents.matcher import candidate_years, resolve_requirement_status
from hireflow_api.db import count_rows, delete_rows, fetch_in, fetch_many, fetch_one, insert_row, insert_rows, update_rows
from hireflow_api.models import Candidate, Claim, Decision, Document, EvidenceItem, Gap, InterviewPlan, Job, MatchResult, PipelineRun, PlannedQuestion, ProbeResult, Profile, Report, Requirement, Transcript, TranscriptTurn, utcnow
from hireflow_api.queue import enqueue_analyze, enqueue_extract, enqueue_match, enqueue_parse, enqueue_plan, enqueue_report
from hireflow_api.storage import get_store
from hireflow_domain.enums import (
    DocumentKind,
    DocumentOwnerType,
    EvidenceDimension,
    EvidenceSource,
    EvidenceStrength,
    InterviewPlanStatus,
    OverallMatch,
    PipelineGraph,
    PipelineStatus,
    MatchStatus,
    ProbeVerdict,
    QuestionSource,
    ReportKind,
    RequirementPriority,
    TranscriptSource,
    TranscriptStatus,
)
from hireflow_domain.fit import score_overall_match
from hireflow_domain.schemas import (
    CandidatePublic,
    ClaimPublic,
    DimensionFlags,
    DocumentPublic,
    GapPublic,
    InterviewPlanPublic,
    InterviewPlanResponse,
    JobDetail,
    JobSummary,
    MatrixCandidate,
    MatrixCell,
    MatrixResponse,
    MatchResultPublic,
    PipelineRunPublic,
    PlannedQuestionPublic,
    ProbeResultPublic,
    ProfilePublic,
    ReportPublic,
    RequirementPublic,
    ScreenStatus,
    SourceSpan,
    TranscriptDetail,
    TranscriptPublic,
    TranscriptTurnPatch,
    TranscriptTurnPublic,
    ContradictionRow,
    CoverageRow,
    DecisionCreate,
    DecisionPublic,
    EvidenceItemPublic,
    EvidenceReportBody,
    EvidenceReportResponse,
    RequirementAssessment,
    UnresolvedGap,
    UploadResult,
)

ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".vtt", ".md", ".rtf"}
ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/vtt",
    "text/markdown",
    "application/octet-stream",
}


class UploadError(ValueError):
    pass


def _parse(model, row: dict | None):
    if row is None:
        return None
    return model.model_validate(row)


def _public_run(run: PipelineRun | None) -> PipelineRunPublic | None:
    if run is None:
        return None
    return PipelineRunPublic.model_validate(run)


def _requirement_priority(requirement: RequirementPublic | Requirement | None) -> RequirementPriority:
    if requirement is None:
        return RequirementPriority.unclear_priority
    raw = requirement.priority
    if isinstance(raw, RequirementPriority):
        return raw
    return RequirementPriority(raw)


def _overall_match_from_rows(
    rows: list[dict],
    requirements: dict[str, RequirementPublic] | dict[str, Requirement],
) -> OverallMatch | None:
    items = [
        (MatchStatus(row["status"]), _requirement_priority(requirements.get(row["requirement_id"])))
        for row in rows
        if row.get("status")
    ]
    return score_overall_match(items)


async def _overall_match_map(*, job_id: str, candidate_ids: list[str]) -> dict[str, OverallMatch | None]:
    requirements = {
        Requirement.model_validate(row).id: Requirement.model_validate(row)
        for row in await fetch_many("requirements", job_id=job_id)
    }
    grouped: dict[str, list[dict]] = {candidate_id: [] for candidate_id in candidate_ids}
    for row in await fetch_many("match_results", job_id=job_id):
        grouped.setdefault(row["candidate_id"], []).append(row)
    result: dict[str, OverallMatch | None] = {}
    for candidate_id in candidate_ids:
        rows = grouped.get(candidate_id, [])
        if not rows:
            result[candidate_id] = None
            continue
        candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id))
        if candidate is None:
            result[candidate_id] = _overall_match_from_rows(rows, requirements)
            continue
        resolved = await _resolved_match_rows(candidate=candidate, rows=rows, persist=True)
        resolved_rows = [{"requirement_id": item.requirement_id, "status": item.status} for item in resolved]
        result[candidate_id] = _overall_match_from_rows(resolved_rows, requirements)
    return result


def _public_document(document: Document | None, run: PipelineRun | None) -> DocumentPublic | None:
    if document is None:
        return None
    payload = DocumentPublic.model_validate(document)
    payload.extract_run = _public_run(run)
    return payload


async def latest_document(*, owner_type: str, owner_id: str, kind: str) -> Document | None:
    rows = await fetch_many(
        "documents",
        owner_type=owner_type,
        owner_id=owner_id,
        kind=kind,
        order="version",
        desc=True,
        limit=1,
    )
    return _parse(Document, rows[0] if rows else None)


async def latest_run(*, subject_type: str, subject_id: str, graph: str | None = None) -> PipelineRun | None:
    filters: dict = {"subject_type": subject_type, "subject_id": subject_id}
    if graph:
        filters["graph"] = graph
    rows = await fetch_many("pipeline_runs", order="created_at", desc=True, limit=1, **filters)
    return _parse(PipelineRun, rows[0] if rows else None)


async def latest_run_for_document(document_id: str) -> PipelineRun | None:
    return await latest_run(subject_type="document", subject_id=document_id, graph="extract")


async def get_run(run_id: str) -> PipelineRun | None:
    return _parse(PipelineRun, await fetch_one("pipeline_runs", id=run_id))


async def list_jobs(org_id: str) -> list[JobSummary]:
    jobs = [_parse(Job, row) for row in await fetch_many("jobs", org_id=org_id, order="created_at", desc=True)]
    summaries: list[JobSummary] = []
    for job in jobs:
        assert job is not None
        candidate_count = await count_rows("candidates", job_id=job.id)
        jd = await latest_document(owner_type="job", owner_id=job.id, kind="jd")
        summaries.append(
            JobSummary(
                id=job.id,
                title=job.title,
                status=job.status,  # type: ignore[arg-type]
                created_at=job.created_at,
                candidate_count=candidate_count,
                has_jd=jd is not None,
            )
        )
    return summaries


def _span(raw: dict | None) -> SourceSpan | None:
    if not raw:
        return None
    return SourceSpan.model_validate(raw)


def _public_requirement(row: Requirement) -> RequirementPublic:
    return RequirementPublic(
        id=row.id,
        job_id=row.job_id,
        document_version=row.document_version,
        text=row.text,
        normalized_label=row.normalized_label,
        category=row.category,  # type: ignore[arg-type]
        priority=row.priority,  # type: ignore[arg-type]
        source_quote=row.source_quote,
        source_span=_span(row.source_span),
        recruiter_edited=bool(row.recruiter_edited),
        sort_order=row.sort_order,
    )


def _public_claim(row: Claim) -> ClaimPublic:
    return ClaimPublic(
        id=row.id,
        candidate_id=row.candidate_id,
        kind=row.kind,  # type: ignore[arg-type]
        text=row.text,
        skill_label=row.skill_label,
        years=row.years,
        source_span=_span(row.source_span),
        quote=row.quote,
    )


def _public_profile(row: Profile | None) -> ProfilePublic | None:
    if row is None:
        return None
    return ProfilePublic(
        id=row.id,
        candidate_id=row.candidate_id,
        full_name=row.full_name,
        email=row.email,
        summary=row.summary,
        years_experience=row.years_experience,
        education=list(row.education or []),
        roles=list(row.roles or []),
        skills_listed=list(row.skills_listed or []),
        parser_warnings=list(row.parser_warnings or []),
    )


async def list_requirements(*, job_id: str) -> list[RequirementPublic]:
    rows = await fetch_many("requirements", job_id=job_id, order="sort_order")
    return [_public_requirement(Requirement.model_validate(row)) for row in rows]


async def _candidate_parse_bits(
    candidate_id: str,
) -> tuple[ProfilePublic | None, list[ClaimPublic], PipelineRunPublic | None, PipelineRunPublic | None]:
    profile = _parse(Profile, await fetch_one("profiles", candidate_id=candidate_id))
    claims = [
        _public_claim(Claim.model_validate(row))
        for row in await fetch_many("claims", candidate_id=candidate_id, order="kind")
    ]
    parse_run = await latest_run(subject_type="candidate", subject_id=candidate_id, graph="screening")
    match_run = await latest_run(subject_type="match", subject_id=candidate_id, graph="screening")
    return _public_profile(profile), claims, _public_run(parse_run), _public_run(match_run)


async def get_job_detail(*, org_id: str, job_id: str) -> JobDetail | None:
    job = _parse(Job, await fetch_one("jobs", id=job_id, org_id=org_id))
    if job is None:
        return None
    jd = await latest_document(owner_type="job", owner_id=job.id, kind="jd")
    jd_run = await latest_run_for_document(jd.id) if jd else None
    parse_run = await latest_run(subject_type="job", subject_id=job.id, graph="screening")
    candidates = [
        Candidate.model_validate(row)
        for row in await fetch_many("candidates", job_id=job.id, order="created_at", desc=True)
    ]
    fit_by_id = await _overall_match_map(job_id=job.id, candidate_ids=[item.id for item in candidates])
    candidate_models: list[CandidatePublic] = []
    for candidate in candidates:
        resume = await latest_document(owner_type="candidate", owner_id=candidate.id, kind="resume")
        resume_run = await latest_run_for_document(resume.id) if resume else None
        profile, claims, cand_parse, cand_match = await _candidate_parse_bits(candidate.id)
        candidate_models.append(
            CandidatePublic(
                id=candidate.id,
                job_id=candidate.job_id,
                full_name=candidate.full_name,
                email=candidate.email,
                created_at=candidate.created_at,
                resume=_public_document(resume, resume_run),
                profile=profile,
                claims=claims,
                parse_run=cand_parse,
                match_run=cand_match,
                overall_match=fit_by_id.get(candidate.id),
            )
        )
    return JobDetail(
        id=job.id,
        title=job.title,
        status=job.status,  # type: ignore[arg-type]
        created_at=job.created_at,
        jd=_public_document(jd, jd_run),
        candidates=candidate_models,
        requirements=await list_requirements(job_id=job.id),
        parse_run=_public_run(parse_run),
    )


async def get_candidate_public(*, org_id: str, candidate_id: str) -> CandidatePublic | None:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        return None
    resume = await latest_document(owner_type="candidate", owner_id=candidate.id, kind="resume")
    resume_run = await latest_run_for_document(resume.id) if resume else None
    profile, claims, parse_run, match_run = await _candidate_parse_bits(candidate.id)
    requirement_models = {
        Requirement.model_validate(row).id: Requirement.model_validate(row)
        for row in await fetch_many("requirements", job_id=candidate.job_id)
    }
    match_rows = await fetch_many("match_results", candidate_id=candidate.id)
    if match_rows and profile is not None:
        resolved = await _resolved_match_rows(candidate=candidate, rows=match_rows, persist=True)
        overall_rows = [{"requirement_id": item.requirement_id, "status": item.status} for item in resolved]
    else:
        overall_rows = match_rows
    return CandidatePublic(
        id=candidate.id,
        job_id=candidate.job_id,
        full_name=candidate.full_name,
        email=candidate.email,
        created_at=candidate.created_at,
        resume=_public_document(resume, resume_run),
        profile=profile,
        claims=claims,
        parse_run=parse_run,
        match_run=match_run,
        overall_match=_overall_match_from_rows(overall_rows, requirement_models),
    )


async def create_job(*, org_id: str, user_id: str, title: str) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        org_id=org_id,
        title=title.strip(),
        status="draft",
        created_by=user_id,
        created_at=utcnow(),
    )
    return Job.model_validate(await insert_row("jobs", job))


async def create_candidate(*, org_id: str, job_id: str, full_name: str, email: str | None) -> Candidate:
    candidate = Candidate(
        id=str(uuid.uuid4()),
        org_id=org_id,
        job_id=job_id,
        full_name=full_name.strip(),
        email=email.strip() if email else None,
        created_at=utcnow(),
    )
    return Candidate.model_validate(await insert_row("candidates", candidate))


def _validate_upload(filename: str, mime: str, size: int, max_bytes: int) -> None:
    from pathlib import Path

    suffix = Path(filename).suffix.lower()
    if size > max_bytes:
        raise UploadError("file is too large")
    if suffix not in ALLOWED_SUFFIXES and mime not in ALLOWED_MIMES:
        raise UploadError("unsupported file type")
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadError("unsupported file type")


async def store_and_extract(
    *,
    org_id: str,
    user_id: str,
    owner_type: DocumentOwnerType,
    owner_id: str,
    kind: DocumentKind,
    filename: str,
    mime: str,
    content: bytes,
    max_bytes: int,
    job_id: str,
    candidate_id: str | None = None,
) -> UploadResult:
    _validate_upload(filename, mime or "application/octet-stream", len(content), max_bytes)
    digest = hashlib.sha256(content).hexdigest()

    existing = _parse(
        Document,
        await fetch_one(
            "documents",
            org_id=org_id,
            owner_type=owner_type.value,
            owner_id=owner_id,
            kind=kind.value,
            sha256=digest,
        ),
    )
    if existing is not None:
        run = await _enqueue_extract_run(org_id=org_id, document=existing)
        return UploadResult(document=_public_document(existing, run), run=_public_run(run), reused=True)  # type: ignore[arg-type]

    current = await latest_document(owner_type=owner_type.value, owner_id=owner_id, kind=kind.value)
    version = (current.version + 1) if current else 1
    document_id = str(uuid.uuid4())
    if kind == DocumentKind.jd:
        storage_key = f"org/{org_id}/jobs/{job_id}/jd/{document_id}/original"
    elif kind == DocumentKind.transcript:
        storage_key = f"org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/transcripts/{document_id}/original"
    else:
        storage_key = f"org/{org_id}/jobs/{job_id}/candidates/{candidate_id}/resume/{document_id}/original"

    try:
        await get_store().put(storage_key, content, mime or "application/octet-stream")
    except Exception as exc:
        raise UploadError(f"Could not save file: {exc}") from exc
    document = Document(
        id=document_id,
        org_id=org_id,
        owner_type=owner_type.value,
        owner_id=owner_id,
        kind=kind.value,
        storage_key=storage_key,
        original_filename=filename,
        mime=mime or "application/octet-stream",
        sha256=digest,
        extracted_text=None,
        version=version,
        uploaded_by=user_id,
        created_at=utcnow(),
    )
    document = Document.model_validate(await insert_row("documents", document))
    run = await _enqueue_extract_run(org_id=org_id, document=document)
    return UploadResult(document=_public_document(document, run), run=_public_run(run), reused=False)  # type: ignore[arg-type]


async def _enqueue_extract_run(*, org_id: str, document: Document) -> PipelineRun:
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.extract.value,
        subject_type="document",
        subject_id=document.id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await enqueue_extract(document.id, run.id)
    return run


async def start_parse(*, org_id: str, kind: str, subject_type: str, subject_id: str) -> PipelineRun:
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.screening.value,
        subject_type=subject_type,
        subject_id=subject_id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await enqueue_parse(kind, subject_id, run.id)
    return run


async def patch_requirement(*, org_id: str, requirement_id: str, body) -> RequirementPublic | None:
    row = _parse(Requirement, await fetch_one("requirements", id=requirement_id, org_id=org_id))
    if row is None:
        raise KeyError(requirement_id)
    if body.dropped:
        await delete_rows("requirements", id=requirement_id, org_id=org_id)
        return None
    updates: dict = {"recruiter_edited": True}
    if body.text is not None:
        updates["text"] = body.text.strip()
    if body.normalized_label is not None:
        updates["normalized_label"] = body.normalized_label.strip()
    if body.category is not None:
        updates["category"] = body.category.value
    if body.priority is not None:
        updates["priority"] = body.priority.value
    if body.sort_order is not None:
        updates["sort_order"] = body.sort_order
    updated = await update_rows("requirements", updates, id=requirement_id, org_id=org_id)
    if not updated:
        raise KeyError(requirement_id)
    return _public_requirement(Requirement.model_validate(updated[0]))


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_ID_REF_RE = re.compile(
    r"\s*[\(\[]?\s*id\s+" + _UUID_RE.pattern + r"\s*[\)\]]?",
    re.IGNORECASE,
)


def scrub_internal_ids(text: str | None) -> str:
    if not text:
        return ""
    cleaned = _ID_REF_RE.sub("", text)
    cleaned = re.sub(r"\s*[\(\[]\s*" + _UUID_RE.pattern + r"\s*[\)\]]", "", cleaned)
    cleaned = _UUID_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    return cleaned.strip()


def _claim_quotes(claims: list[Claim], supporting_ids: list[str]) -> list[str]:
    by_id = {claim.id: claim for claim in claims}
    quotes: list[str] = []
    for claim_id in supporting_ids:
        claim = by_id.get(claim_id)
        if claim is None:
            continue
        quote = (claim.quote or claim.text or "").strip()
        if quote:
            quotes.append(quote)
    return quotes


def _profile_dict(row: Profile | None) -> dict | None:
    if row is None:
        return None
    return {
        "full_name": row.full_name,
        "summary": row.summary,
        "years_experience": row.years_experience,
        "education": list(row.education or []),
        "skills_listed": list(row.skills_listed or []),
        "roles": list(row.roles or []),
    }


def _claim_dicts(claims: list[Claim]) -> list[dict]:
    return [
        {
            "id": claim.id,
            "kind": claim.kind,
            "text": claim.text,
            "skill_label": claim.skill_label,
            "years": claim.years,
            "quote": claim.quote,
        }
        for claim in claims
    ]


def _resolved_match_row(
    row: MatchResult,
    requirement: Requirement | None,
    *,
    profile: dict | None,
    claim_dicts: list[dict],
    experience_years: float | None,
) -> MatchResult:
    if requirement is None or profile is None:
        return row
    flags = DimensionFlags.model_validate(row.dimension_flags or {})
    resolved = resolve_requirement_status(
        requirement_text=requirement.text,
        normalized_label=requirement.normalized_label or "",
        category=requirement.category,
        profile=profile,
        claims=claim_dicts,
        flags=flags,
        conflicting=False,
        experience_years=experience_years,
    )
    if resolved.value == row.status:
        return row
    return row.model_copy(update={"status": resolved.value})


async def _candidate_match_context(*, candidate: Candidate) -> tuple[
    dict[str, Requirement],
    list[Claim],
    dict | None,
    list[dict],
    float | None,
]:
    requirements = {
        Requirement.model_validate(row).id: Requirement.model_validate(row)
        for row in await fetch_many("requirements", job_id=candidate.job_id)
    }
    claims = [Claim.model_validate(row) for row in await fetch_many("claims", candidate_id=candidate.id)]
    profile = _profile_dict(_parse(Profile, await fetch_one("profiles", candidate_id=candidate.id)))
    claim_dicts = _claim_dicts(claims)
    experience_years = candidate_years(profile, claim_dicts)
    return requirements, claims, profile, claim_dicts, experience_years


async def _resolved_match_rows(
    *,
    candidate: Candidate,
    rows: list[dict],
    requirements: dict[str, Requirement] | None = None,
    claims: list[Claim] | None = None,
    profile: dict | None = None,
    claim_dicts: list[dict] | None = None,
    experience_years: float | None = None,
    persist: bool = False,
) -> list[MatchResult]:
    if requirements is None or claims is None or profile is None or claim_dicts is None:
        requirements, claims, profile, claim_dicts, experience_years = await _candidate_match_context(
            candidate=candidate
        )
    resolved_rows: list[MatchResult] = []
    pending_updates: list[tuple[str, str]] = []
    for row in rows:
        requirement = requirements.get(row["requirement_id"])
        match = _resolved_match_row(
            MatchResult.model_validate(row),
            requirement,
            profile=profile,
            claim_dicts=claim_dicts,
            experience_years=experience_years,
        )
        resolved_rows.append(match)
        if persist and match.status != row["status"]:
            pending_updates.append((match.id, match.status))
    if persist and pending_updates:
        for match_id, status in pending_updates:
            await update_rows("match_results", {"status": status}, id=match_id)
    return resolved_rows


def _public_match(row: MatchResult, requirement: Requirement | None, claims: list[Claim]) -> MatchResultPublic:
    supporting = list(row.supporting_claim_ids or [])
    flags = DimensionFlags.model_validate(row.dimension_flags or {})
    quotes = _claim_quotes(claims, supporting)
    if not quotes and row.status == "MISSING":
        quotes = []
    return MatchResultPublic(
        id=row.id,
        job_id=row.job_id,
        candidate_id=row.candidate_id,
        requirement_id=row.requirement_id,
        status=row.status,  # type: ignore[arg-type]
        confidence=row.confidence,
        rationale=scrub_internal_ids(row.rationale),
        dimension_flags=flags,
        supporting_claim_ids=supporting,
        run_id=row.run_id,
        requirement_label=requirement.normalized_label if requirement else "",
        requirement_priority=requirement.priority if requirement else None,  # type: ignore[arg-type]
        quotes=quotes,
        status_after_interview=row.status_after_interview,  # type: ignore[arg-type]
    )


async def start_match(*, org_id: str, candidate_id: str) -> PipelineRun:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    requirements = await fetch_many("requirements", job_id=candidate.job_id, limit=1)
    if not requirements:
        raise ValueError("Parse and confirm JD requirements before matching")
    profile = await fetch_one("profiles", candidate_id=candidate_id)
    claims = await fetch_many("claims", candidate_id=candidate_id, limit=1)
    if profile is None and not claims:
        raise ValueError("Parse the resume before matching")
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.screening.value,
        subject_type="match",
        subject_id=candidate_id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await enqueue_match(candidate_id, run.id)
    return run


async def list_matches(*, org_id: str, candidate_id: str) -> list[MatchResultPublic]:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    rows = await fetch_many("match_results", candidate_id=candidate_id)
    requirements, claims, profile, claim_dicts, experience_years = await _candidate_match_context(candidate=candidate)
    resolved_rows = await _resolved_match_rows(
        candidate=candidate,
        rows=rows,
        requirements=requirements,
        claims=claims,
        profile=profile,
        claim_dicts=claim_dicts,
        experience_years=experience_years,
        persist=True,
    )
    by_id = {item.id: item for item in resolved_rows}
    return [
        _public_match(
            by_id.get(row["id"], MatchResult.model_validate(row)),
            requirements.get(row["requirement_id"]),
            claims,
        )
        for row in rows
    ]


async def list_gaps(*, org_id: str, candidate_id: str) -> list[GapPublic]:
    matches = await list_matches(org_id=org_id, candidate_id=candidate_id)
    if not matches:
        return []
    by_match = {item.id: item for item in matches}
    rows = await fetch_in("gaps", "match_result_id", list(by_match))
    if not rows:
        from hireflow_agents.gap_analyst import default_goal, default_severity, default_themes

        synthesized: list[dict] = []
        for match in matches:
            if match.status == MatchStatus.MATCHED:
                continue
            priority = (
                match.requirement_priority.value
                if match.requirement_priority
                else RequirementPriority.unclear_priority.value
            )
            if priority != RequirementPriority.must_have.value:
                continue
            synthesized.append(
                {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "match_result_id": match.id,
                    "severity": default_severity(match.status, priority).value,
                    "investigation_goal": default_goal(match.requirement_label, match.status),
                    "suggested_probe_themes": default_themes(match.status),
                    "deal_breaker": False,
                    "skip_probe": False,
                }
            )
        if synthesized:
            await insert_rows("gaps", synthesized)
            rows = synthesized
    gaps: list[GapPublic] = []
    for row in rows:
        match = by_match.get(row["match_result_id"])
        gap = Gap.model_validate(row)
        gaps.append(
            GapPublic(
                id=gap.id,
                match_result_id=gap.match_result_id,
                requirement_id=match.requirement_id if match else "",
                requirement_label=match.requirement_label if match else "",
                status=match.status if match else None,
                severity=gap.severity,  # type: ignore[arg-type]
                investigation_goal=scrub_internal_ids(gap.investigation_goal),
                suggested_probe_themes=list(gap.suggested_probe_themes or []),
                deal_breaker=bool(gap.deal_breaker),
                skip_probe=bool(gap.skip_probe),
            )
        )
    order = {"blocker": 0, "high": 1, "medium": 2, "low": 3}
    gaps.sort(key=lambda item: order.get(item.severity.value, 9))
    return gaps


async def patch_gap(*, org_id: str, gap_id: str, body) -> GapPublic:
    row = await fetch_one("gaps", id=gap_id, org_id=org_id)
    if row is None:
        raise KeyError(gap_id)
    updates: dict = {}
    if body.deal_breaker is not None:
        updates["deal_breaker"] = body.deal_breaker
    if body.skip_probe is not None:
        updates["skip_probe"] = body.skip_probe
    if updates:
        updated = await update_rows("gaps", updates, id=gap_id, org_id=org_id)
        row = updated[0] if updated else row
    match = _parse(MatchResult, await fetch_one("match_results", id=row["match_result_id"]))
    requirement = None
    if match:
        requirement = _parse(Requirement, await fetch_one("requirements", id=match.requirement_id))
    gap = Gap.model_validate(row)
    return GapPublic(
        id=gap.id,
        match_result_id=gap.match_result_id,
        requirement_id=match.requirement_id if match else "",
        requirement_label=requirement.normalized_label if requirement else "",
        status=match.status if match else None,  # type: ignore[arg-type]
        severity=gap.severity,  # type: ignore[arg-type]
        investigation_goal=scrub_internal_ids(gap.investigation_goal),
        suggested_probe_themes=list(gap.suggested_probe_themes or []),
        deal_breaker=bool(gap.deal_breaker),
        skip_probe=bool(gap.skip_probe),
    )


async def get_matrix(*, org_id: str, job_id: str) -> MatrixResponse | None:
    job = _parse(Job, await fetch_one("jobs", id=job_id, org_id=org_id))
    if job is None:
        return None
    requirements = await list_requirements(job_id=job_id)
    candidates = [
        Candidate.model_validate(row)
        for row in await fetch_many("candidates", job_id=job_id, order="created_at", desc=True)
    ]
    matches = await fetch_many("match_results", job_id=job_id)
    claims_by_candidate: dict[str, list[Claim]] = {}
    matches_by_candidate: dict[str, list[dict]] = {item.id: [] for item in candidates}
    profiles_by_candidate: dict[str, dict | None] = {}
    claim_dicts_by_candidate: dict[str, list[dict]] = {}
    experience_by_candidate: dict[str, float | None] = {}
    for candidate in candidates:
        claims_by_candidate[candidate.id] = [
            Claim.model_validate(row) for row in await fetch_many("claims", candidate_id=candidate.id)
        ]
        claim_dicts_by_candidate[candidate.id] = _claim_dicts(claims_by_candidate[candidate.id])
        profiles_by_candidate[candidate.id] = _profile_dict(
            _parse(Profile, await fetch_one("profiles", candidate_id=candidate.id))
        )
        experience_by_candidate[candidate.id] = candidate_years(
            profiles_by_candidate[candidate.id],
            claim_dicts_by_candidate[candidate.id],
        )
    cells: list[MatrixCell] = []
    requirement_map = {item.id: item for item in requirements}
    for row in matches:
        match = MatchResult.model_validate(row)
        requirement = requirement_map.get(match.requirement_id)
        match = _resolved_match_row(
            match,
            requirement,
            profile=profiles_by_candidate.get(match.candidate_id),
            claim_dicts=claim_dicts_by_candidate.get(match.candidate_id, []),
            experience_years=experience_by_candidate.get(match.candidate_id),
        )
        matches_by_candidate.setdefault(match.candidate_id, []).append({**row, "status": match.status})
        quotes = _claim_quotes(claims_by_candidate.get(match.candidate_id, []), list(match.supporting_claim_ids or []))
        cells.append(
            MatrixCell(
                candidate_id=match.candidate_id,
                requirement_id=match.requirement_id,
                status=match.status,  # type: ignore[arg-type]
                rationale=scrub_internal_ids(match.rationale),
                quotes=quotes,
            )
        )
    return MatrixResponse(
        job_id=job_id,
        requirements=requirements,
        candidates=[
            MatrixCandidate(
                id=item.id,
                full_name=item.full_name,
                overall_match=_overall_match_from_rows(matches_by_candidate.get(item.id, []), requirement_map),
            )
            for item in candidates
        ],
        cells=cells,
    )


def _status_value(run: object | None) -> str | None:
    if run is None:
        return None
    status = getattr(run, "status", None)
    if status is None:
        return None
    return status.value if hasattr(status, "value") else str(status)


def _run_pending(run: object | None) -> bool:
    status = _status_value(run)
    if status not in {PipelineStatus.queued.value, PipelineStatus.running.value}:
        return False
    started = getattr(run, "started_at", None) if run is not None else None
    if status == PipelineStatus.running.value and started is not None:
        age = (utcnow() - started).total_seconds()
        if age > 600:
            return False
    return True


def _run_failed(run: object | None) -> bool:
    return _status_value(run) == PipelineStatus.failed.value


def _run_succeeded(run: object | None) -> bool:
    return _status_value(run) == PipelineStatus.succeeded.value


def _screen(step: str, message: str, run: PipelineRun | PipelineRunPublic | None = None) -> ScreenStatus:
    public = run if isinstance(run, PipelineRunPublic) else _public_run(run)
    return ScreenStatus(step=step, message=message, run=public)


_SCREEN_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _SCREEN_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _SCREEN_LOCKS[key] = lock
    return lock


async def start_parse_unless_active(
    *,
    org_id: str,
    kind: str,
    subject_type: str,
    subject_id: str,
) -> PipelineRun:
    async with _lock_for(f"parse:{subject_type}:{subject_id}"):
        existing = await latest_run(subject_type=subject_type, subject_id=subject_id, graph=PipelineGraph.screening.value)
        if _run_pending(existing) and existing is not None:
            return existing
        return await start_parse(org_id=org_id, kind=kind, subject_type=subject_type, subject_id=subject_id)


async def start_match_unless_active(*, org_id: str, candidate_id: str) -> PipelineRun | None:
    async with _lock_for(f"match:{candidate_id}"):
        existing = await latest_run(subject_type="match", subject_id=candidate_id, graph=PipelineGraph.screening.value)
        if _run_pending(existing) and existing is not None:
            return existing
        try:
            return await start_match(org_id=org_id, candidate_id=candidate_id)
        except ValueError:
            return None


async def continue_after_extract(*, document: Document) -> None:
    if document.kind == DocumentKind.jd.value:
        await start_parse_unless_active(
            org_id=document.org_id,
            kind="jd",
            subject_type="job",
            subject_id=document.owner_id,
        )
        return
    if document.kind == DocumentKind.resume.value:
        await start_parse_unless_active(
            org_id=document.org_id,
            kind="resume",
            subject_type="candidate",
            subject_id=document.owner_id,
        )
        return
    if document.kind == DocumentKind.transcript.value:
        row = await fetch_one("transcripts", document_id=document.id, org_id=document.org_id)
        if row:
            await start_analyze_unless_active(org_id=document.org_id, transcript_id=row["id"])


async def continue_after_parse(*, org_id: str, kind: str, subject_id: str) -> None:
    if kind == "jd":
        rows = await fetch_many("candidates", job_id=subject_id)
        for row in rows:
            await start_match_unless_active(org_id=org_id, candidate_id=row["id"])
        return
    if kind == "resume":
        await start_match_unless_active(org_id=org_id, candidate_id=subject_id)


async def advance_candidate_screen(*, org_id: str, candidate_id: str, force: bool = False) -> ScreenStatus:
    public = await get_candidate_public(org_id=org_id, candidate_id=candidate_id)
    if public is None:
        raise KeyError(candidate_id)
    job = await get_job_detail(org_id=org_id, job_id=public.job_id)
    if job is None:
        raise KeyError(candidate_id)

    resume = public.resume
    if _run_pending(resume.extract_run if resume else None):
        return _screen("extract_resume", "Reading the resume…", resume.extract_run if resume else None)
    if not resume or not (resume.extracted_text or "").strip():
        if resume and _run_failed(resume.extract_run):
            return _screen(
                "blocked",
                resume.extract_run.error if resume.extract_run else "Could not read the resume.",
                resume.extract_run,
            )
        return _screen("blocked", "Upload a resume on the job page first.")

    jd = job.jd
    if _run_pending(jd.extract_run if jd else None):
        return _screen("extract_jd", "Reading the job description…", jd.extract_run if jd else None)
    if not jd or not (jd.extracted_text or "").strip():
        if jd and _run_failed(jd.extract_run):
            return _screen("blocked", jd.extract_run.error if jd.extract_run else "Could not read the JD.", jd.extract_run)
        return _screen("blocked", "Upload a job description on the job page first.")

    if not job.requirements:
        if _run_pending(job.parse_run):
            return _screen("parse_jd", "Extracting requirements from the JD…", job.parse_run)
        if _run_failed(job.parse_run) and not force:
            return _screen("blocked", job.parse_run.error if job.parse_run else "Could not parse the JD.", job.parse_run)
        if _run_succeeded(job.parse_run) and not force:
            return _screen("blocked", "No requirements found in the JD. Re-parse from the job page.", job.parse_run)
        run = await start_parse_unless_active(org_id=org_id, kind="jd", subject_type="job", subject_id=job.id)
        return _screen("parse_jd", "Extracting requirements from the JD…", run)

    if public.profile is None and not public.claims:
        if _run_pending(public.parse_run):
            return _screen("parse_resume", "Reading claims from the resume…", public.parse_run)
        if _run_failed(public.parse_run) and not force:
            return _screen(
                "blocked",
                public.parse_run.error if public.parse_run else "Could not parse the resume.",
                public.parse_run,
            )
        run = await start_parse_unless_active(
            org_id=org_id,
            kind="resume",
            subject_type="candidate",
            subject_id=candidate_id,
        )
        return _screen("parse_resume", "Reading claims from the resume…", run)

    if _run_pending(public.match_run):
        return _screen("match", "Matching the resume to the JD…", public.match_run)
    if not force:
        if public.overall_match is not None:
            return _screen("ready", "Match and gap analysis are ready.", public.match_run)
        match_rows = await fetch_many("match_results", candidate_id=candidate_id)
        if match_rows:
            return _screen("ready", "Match and gap analysis are ready.", public.match_run)
        if _run_succeeded(public.match_run):
            return _screen("ready", "Match and gap analysis are ready.", public.match_run)
        if _run_failed(public.match_run):
            return _screen("blocked", public.match_run.error if public.match_run else "Match failed.", public.match_run)
    elif force and _run_pending(public.parse_run):
        return _screen("parse_resume", "Reading claims from the resume…", public.parse_run)

    run = await start_match(org_id=org_id, candidate_id=candidate_id)
    return _screen("match", "Matching the resume to the JD…", run)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return cleaned or "candidate"


def _append_requirement_match_brief(lines: list[str], matches: list) -> None:
    if not matches:
        lines.append("No match results.")
        lines.append("")
        return
    for match in matches:
        priority = (match.requirement_priority.value if match.requirement_priority else "unspecified").replace(
            "_", " "
        )
        lines.append(f"### {match.requirement_label} — {match.status.value}")
        lines.append("")
        lines.append(f"Priority: {priority}")
        lines.append("")
        rationale = (match.rationale or "").strip()
        quotes = [quote.strip() for quote in (match.quotes or []) if quote and quote.strip()]
        if rationale:
            lines.append(rationale)
            lines.append("")
        if quotes:
            for quote in quotes:
                lines.append(f"> {quote}")
                lines.append("")
        elif not rationale:
            lines.append("No evidence found.")
            lines.append("")


async def screening_brief_file(*, org_id: str, candidate_id: str) -> tuple[str, bytes]:
    public = await get_candidate_public(org_id=org_id, candidate_id=candidate_id)
    if public is None:
        raise KeyError(candidate_id)
    if not _run_succeeded(public.match_run):
        matches = await list_matches(org_id=org_id, candidate_id=candidate_id)
        if not matches:
            raise ValueError("Match and gap analysis are not ready yet")
    job = await get_job_detail(org_id=org_id, job_id=public.job_id)
    if job is None:
        raise KeyError(candidate_id)
    matches = await list_matches(org_id=org_id, candidate_id=candidate_id)
    gaps = await list_gaps(org_id=org_id, candidate_id=candidate_id)
    generated = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Screening brief: {public.full_name} — {job.title}",
        "",
        f"Generated: {generated}",
        f"Overall match: {public.overall_match.value.replace('_', ' ').title()} match" if public.overall_match else "Overall match: not scored",
        "",
        "This file is the JD match and gap analysis for this candidate.",
        "",
        "## Requirement match",
        "",
    ]
    _append_requirement_match_brief(lines, matches)
    lines.extend(["## Gaps analysis", ""])
    if not gaps:
        lines.append("No gaps. Every must-have is MATCHED.")
        lines.append("")
    for gap in gaps:
        status = gap.status.value if gap.status else "UNCLEAR"
        lines.append(f"### {gap.requirement_label} — {status} ({gap.severity.value})")
        lines.append("")
        lines.append(gap.investigation_goal.strip())
        lines.append("")
        if gap.suggested_probe_themes:
            lines.append("Probe themes: " + "; ".join(gap.suggested_probe_themes))
            lines.append("")
        lines.append("")
    body = "\n".join(lines).encode("utf-8")
    filename = f"{_safe_filename(public.full_name)}-{_safe_filename(job.title)}-screening-brief.md"
    run_id = public.match_run.id if public.match_run else "latest"
    key = f"org/{org_id}/jobs/{job.id}/candidates/{public.id}/reports/{run_id}/screening-brief.md"
    try:
        await get_store().put(key, body, "text/markdown")
    except Exception:
        pass
    return filename, body


async def _current_plan_row(*, org_id: str, candidate_id: str) -> dict | None:
    rows = await fetch_many("interview_plans", org_id=org_id, candidate_id=candidate_id, order="version", desc=True)
    for row in rows:
        if row.get("status") != InterviewPlanStatus.superseded.value:
            return row
    return None


def _evidence_targets(raw: list | None) -> list[EvidenceDimension]:
    targets: list[EvidenceDimension] = []
    for item in raw or []:
        try:
            targets.append(EvidenceDimension(item))
        except ValueError:
            continue
    return targets


def _public_report(row: Report | None) -> ReportPublic | None:
    if row is None:
        return None
    return ReportPublic(
        id=row.id,
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        plan_id=row.plan_id,
        kind=row.kind,  # type: ignore[arg-type]
        version=row.version,
        original_filename=row.original_filename,
        mime=row.mime,
        created_at=row.created_at,
    )


async def _public_question(row: PlannedQuestion, *, matches: list) -> PlannedQuestionPublic:
    match = next((item for item in matches if item.requirement_id == row.requirement_id), None)
    return PlannedQuestionPublic(
        id=row.id,
        plan_id=row.plan_id,
        requirement_id=row.requirement_id,
        requirement_label=match.requirement_label if match else "",
        match_status=match.status if match else None,
        sort_order=row.sort_order,
        prompt=scrub_internal_ids(row.prompt),
        planned_followups=[scrub_internal_ids(item) for item in (row.planned_followups or [])],
        evidence_target=_evidence_targets(row.evidence_target),
        source=row.source,  # type: ignore[arg-type]
        dropped=bool(row.dropped),
    )


async def _public_plan(*, org_id: str, row: dict) -> InterviewPlanPublic:
    plan = InterviewPlan.model_validate(row)
    matches = await list_matches(org_id=org_id, candidate_id=plan.candidate_id)
    questions = [
        await _public_question(PlannedQuestion.model_validate(item), matches=matches)
        for item in await fetch_many("planned_questions", plan_id=plan.id, order="sort_order")
        if not item.get("dropped")
    ]
    report = _parse(Report, await fetch_one("reports", id=plan.brief_report_id)) if plan.brief_report_id else None
    run = _parse(PipelineRun, await fetch_one("pipeline_runs", id=plan.run_id)) if plan.run_id else None
    return InterviewPlanPublic(
        id=plan.id,
        candidate_id=plan.candidate_id,
        job_id=plan.job_id,
        status=plan.status,  # type: ignore[arg-type]
        version=plan.version,
        brief_report=_public_report(report),
        questions=questions,
        run=_public_run(run),
        created_at=plan.created_at,
    )


async def get_interview_plan(*, org_id: str, candidate_id: str) -> InterviewPlanResponse:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    run = await latest_run(subject_type="plan", subject_id=candidate_id, graph="screening")
    row = await _current_plan_row(org_id=org_id, candidate_id=candidate_id)
    plan = await _public_plan(org_id=org_id, row=row) if row else None
    return InterviewPlanResponse(plan=plan, run=_public_run(run))


async def start_plan(*, org_id: str, candidate_id: str) -> PipelineRun:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    matches = await fetch_many("match_results", candidate_id=candidate_id, limit=1)
    if not matches:
        raise ValueError("Match the resume to the JD before generating an interview plan")
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.screening.value,
        subject_type="plan",
        subject_id=candidate_id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await enqueue_plan(candidate_id, run.id)
    return run


async def start_plan_unless_active(*, org_id: str, candidate_id: str) -> PipelineRun | None:
    async with _lock_for(f"plan:{candidate_id}"):
        existing = await latest_run(subject_type="plan", subject_id=candidate_id, graph=PipelineGraph.screening.value)
        if _run_pending(existing) and existing is not None:
            return existing
        try:
            return await start_plan(org_id=org_id, candidate_id=candidate_id)
        except (KeyError, ValueError):
            return None


def _interview_brief_markdown(
    *,
    candidate_name: str,
    job_title: str,
    overall: str,
    matches: list,
    gaps: list,
    questions: list[PlannedQuestionPublic],
) -> str:
    generated = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Interview questions: {candidate_name} — {job_title}",
        "",
        f"Generated: {generated}",
        f"Overall match: {overall}",
        "",
        "Use these questions in an external interview. HireFlow does not conduct the interview.",
        "",
        "## All questions",
        "",
    ]
    numbered: list[str] = []
    for question in questions:
        status = question.match_status or MatchStatus.UNCLEAR
        extras = default_followups(question.requirement_label or "this requirement", status, [])
        pack = [question.prompt.strip(), *[item.strip() for item in question.planned_followups if item.strip()]]
        for extra in extras:
            if extra not in pack:
                pack.append(extra)
        numbered.extend(pack)
    if not numbered:
        lines.append("No interview questions. Remaining must-haves are MATCHED or skipped.")
        lines.append("")
    else:
        for index, prompt in enumerate(numbered, start=1):
            lines.append(f"{index}. {prompt}")
            lines.append("")
    lines.extend(["## Questions by requirement", ""])
    if not questions:
        lines.append("No interview questions.")
        lines.append("")
    for question in questions:
        status = question.match_status.value if question.match_status else "UNCLEAR"
        lines.append(f"### {question.requirement_label} — {status}")
        lines.append("")
        lines.append(f"Primary: {question.prompt.strip()}")
        lines.append("")
        also_ask = [item.strip() for item in question.planned_followups if item.strip()]
        status = question.match_status or MatchStatus.UNCLEAR
        for extra in default_followups(question.requirement_label or "this requirement", status, []):
            if extra not in also_ask and extra != question.prompt.strip():
                also_ask.append(extra)
        if also_ask:
            lines.append("Also ask:")
            for follow in also_ask:
                lines.append(f"- {follow}")
            lines.append("")
        if question.evidence_target:
            lines.append("Evidence target: " + ", ".join(item.value for item in question.evidence_target))
            lines.append("")
    lines.extend(["## Requirement match", ""])
    _append_requirement_match_brief(lines, matches)
    lines.extend(["## Gaps", ""])
    if not gaps:
        lines.append("No gaps. Every must-have is MATCHED.")
        lines.append("")
    for gap in gaps:
        status = gap.status.value if gap.status else "UNCLEAR"
        lines.append(f"### {gap.requirement_label} — {status} ({gap.severity.value})")
        lines.append("")
        lines.append(gap.investigation_goal.strip())
        lines.append("")
    return "\n".join(lines)


async def persist_interview_plan(*, org_id: str, candidate_id: str, plan_id: str, run_id: str | None = None) -> Report:
    public = await get_candidate_public(org_id=org_id, candidate_id=candidate_id)
    if public is None:
        raise KeyError(candidate_id)
    job = await get_job_detail(org_id=org_id, job_id=public.job_id)
    if job is None:
        raise KeyError(candidate_id)
    plan = InterviewPlan.model_validate(await fetch_one("interview_plans", id=plan_id, org_id=org_id))
    matches = await list_matches(org_id=org_id, candidate_id=candidate_id)
    gaps = await list_gaps(org_id=org_id, candidate_id=candidate_id)
    questions = [
        await _public_question(PlannedQuestion.model_validate(item), matches=matches)
        for item in await fetch_many("planned_questions", plan_id=plan_id, order="sort_order")
        if not item.get("dropped")
    ]
    overall = (
        f"{public.overall_match.value.replace('_', ' ').title()} match"
        if public.overall_match
        else "not scored"
    )
    markdown = _interview_brief_markdown(
        candidate_name=public.full_name,
        job_title=job.title,
        overall=overall,
        matches=matches,
        gaps=gaps,
        questions=questions,
    )
    body = markdown.encode("utf-8")
    filename = f"{_safe_filename(public.full_name)}-{_safe_filename(job.title)}-interview-brief.md"
    report_id = str(uuid.uuid4())
    key = f"org/{org_id}/jobs/{job.id}/candidates/{public.id}/reports/{report_id}/interview-brief.md"
    await get_store().put(key, body, "text/markdown")
    report = Report(
        id=report_id,
        org_id=org_id,
        candidate_id=candidate_id,
        job_id=public.job_id,
        plan_id=plan_id,
        kind=ReportKind.interview_brief.value,
        version=plan.version,
        storage_key=key,
        original_filename=filename,
        mime="text/markdown",
        body={"question_count": len(questions), "filename": filename},
        generated_from_run_id=run_id or plan.run_id,
        created_at=utcnow(),
    )
    await insert_row("reports", report)
    await update_rows("interview_plans", {"brief_report_id": report_id}, id=plan_id, org_id=org_id)
    return report


async def patch_planned_question(*, org_id: str, question_id: str, body) -> PlannedQuestionPublic:
    row = await fetch_one("planned_questions", id=question_id, org_id=org_id)
    if row is None:
        raise KeyError(question_id)
    updates: dict = {"source": QuestionSource.recruiter_edited.value}
    if body.prompt is not None:
        updates["prompt"] = scrub_internal_ids(body.prompt)
    if body.planned_followups is not None:
        updates["planned_followups"] = [scrub_internal_ids(item) for item in body.planned_followups]
    if body.sort_order is not None:
        updates["sort_order"] = body.sort_order
    if body.dropped is not None:
        updates["dropped"] = body.dropped
    updated = await update_rows("planned_questions", updates, id=question_id, org_id=org_id)
    row = updated[0] if updated else row
    plan_id = row["plan_id"]
    plan = await fetch_one("interview_plans", id=plan_id, org_id=org_id)
    if plan is None:
        raise KeyError(question_id)
    await persist_interview_plan(org_id=org_id, candidate_id=plan["candidate_id"], plan_id=plan_id)
    matches = await list_matches(org_id=org_id, candidate_id=plan["candidate_id"])
    return await _public_question(PlannedQuestion.model_validate(row), matches=matches)


async def download_report_file(*, org_id: str, report_id: str) -> tuple[str, bytes, str]:
    row = await fetch_one("reports", id=report_id, org_id=org_id)
    if row is None:
        raise KeyError(report_id)
    report = Report.model_validate(row)
    try:
        body = await get_store().get(report.storage_key)
        if body:
            return report.original_filename, body, report.mime
    except Exception:
        pass
    if report.kind == ReportKind.evidence.value and report.body:
        public = await get_candidate_public(org_id=org_id, candidate_id=report.candidate_id)
        job = await get_job_detail(org_id=org_id, job_id=report.job_id) if public else None
        try:
            structured = EvidenceReportBody.model_validate(report.body)
        except Exception as exc:
            raise ValueError("Report file is not available") from exc
        markdown = evidence_report_markdown(
            candidate_name=public.full_name if public else "Candidate",
            job_title=job.title if job else "Role",
            body=structured,
        ).encode("utf-8")
        return report.original_filename, markdown, "text/markdown"
    if report.plan_id:
        rebuilt = await persist_interview_plan(
            org_id=org_id,
            candidate_id=report.candidate_id,
            plan_id=report.plan_id,
            run_id=report.generated_from_run_id,
        )
        body = await get_store().get(rebuilt.storage_key)
        return rebuilt.original_filename, body, rebuilt.mime
    raise ValueError("Report file is not available")


async def download_interview_brief(*, org_id: str, candidate_id: str) -> tuple[str, bytes, str]:
    response = await get_interview_plan(org_id=org_id, candidate_id=candidate_id)
    if response.plan is None:
        raise ValueError("Interview questions are not ready yet. Open the interview kit and generate the plan first.")
    plan_row = await fetch_one("interview_plans", id=response.plan.id, org_id=org_id)
    if plan_row and plan_row.get("brief_report_id"):
        existing = await fetch_one("reports", id=plan_row["brief_report_id"], org_id=org_id)
        if existing:
            report = Report.model_validate(existing)
            body = await get_store().get(report.storage_key)
            if body:
                return report.original_filename, body, report.mime
    run_id = None
    if response.plan.run:
        run_id = response.plan.run.id
    elif response.run:
        run_id = response.run.id
    report = await persist_interview_plan(
        org_id=org_id,
        candidate_id=candidate_id,
        plan_id=response.plan.id,
        run_id=run_id,
    )
    body = await get_store().get(report.storage_key)
    if not body:
        raise ValueError("Interview brief file is not available")
    return report.original_filename, body, report.mime


def _transcript_run(extract_run: PipelineRun | None, analyze_run: PipelineRun | None) -> PipelineRun | None:
    if _run_pending(extract_run):
        return extract_run
    if analyze_run is not None:
        return analyze_run
    return extract_run


def _requirement_label_map(requirements: list[RequirementPublic]) -> dict[str, str]:
    return {item.id: item.normalized_label or item.text for item in requirements}


async def _public_turn(row: dict, labels: dict[str, str]) -> TranscriptTurnPublic:
    turn = TranscriptTurn.model_validate(row)
    return TranscriptTurnPublic(
        id=turn.id,
        speaker=turn.speaker,  # type: ignore[arg-type]
        text=turn.text,
        char_start=turn.char_start,
        char_end=turn.char_end,
        requirement_id=turn.requirement_id,
        requirement_label=labels.get(turn.requirement_id or "", ""),
        question_id=turn.question_id,
        sort_order=turn.sort_order,
        recruiter_edited=bool(turn.recruiter_edited),
    )


def _public_probe(row: dict, labels: dict[str, str]) -> ProbeResultPublic:
    probe = ProbeResult.model_validate(row)
    dims: list[EvidenceDimension] = []
    for item in probe.missing_dimensions or []:
        try:
            dims.append(EvidenceDimension(item))
        except ValueError:
            continue
    return ProbeResultPublic(
        id=probe.id,
        requirement_id=probe.requirement_id,
        requirement_label=labels.get(probe.requirement_id, ""),
        verdict=probe.verdict,  # type: ignore[arg-type]
        missing_dimensions=dims,
        supporting_turn_ids=list(probe.supporting_turn_ids or []),
        remaining_followups=[scrub_internal_ids(item) for item in (probe.remaining_followups or [])],
        rationale=scrub_internal_ids(probe.rationale),
    )


async def _public_transcript(*, org_id: str, row: dict, detail: bool = False) -> TranscriptPublic | TranscriptDetail:
    transcript = Transcript.model_validate(row)
    document = _parse(Document, await fetch_one("documents", id=transcript.document_id)) if transcript.document_id else None
    extract_run = await latest_run_for_document(document.id) if document else None
    analyze_run = (
        _parse(PipelineRun, await fetch_one("pipeline_runs", id=transcript.run_id))
        if transcript.run_id
        else await latest_run(subject_type="transcript", subject_id=transcript.id, graph=PipelineGraph.transcript.value)
    )
    public = TranscriptPublic(
        id=transcript.id,
        candidate_id=transcript.candidate_id,
        job_id=transcript.job_id,
        plan_id=transcript.plan_id,
        source=transcript.source,  # type: ignore[arg-type]
        status=transcript.status,  # type: ignore[arg-type]
        version=transcript.version,
        warnings=list(transcript.warnings or []),
        original_filename=document.original_filename if document else None,
        created_at=transcript.created_at,
        run=_public_run(_transcript_run(extract_run, analyze_run)),
    )
    if not detail:
        return public
    requirements = await list_requirements(job_id=transcript.job_id)
    labels = _requirement_label_map(requirements)
    turns = [
        await _public_turn(item, labels)
        for item in await fetch_many("transcript_turns", transcript_id=transcript.id, order="sort_order")
    ]
    probes = [
        _public_probe(item, labels)
        for item in await fetch_many("probe_results", transcript_id=transcript.id)
    ]
    return TranscriptDetail(
        **public.model_dump(),
        extracted_text=document.extracted_text if document else None,
        turns=turns,
        probes=probes,
    )


async def list_transcripts(*, org_id: str, candidate_id: str) -> list[TranscriptPublic]:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    rows = await fetch_many("transcripts", org_id=org_id, candidate_id=candidate_id, order="version", desc=True)
    return [await _public_transcript(org_id=org_id, row=row) for row in rows]  # type: ignore[misc]


async def get_transcript(*, org_id: str, transcript_id: str) -> TranscriptDetail:
    row = await fetch_one("transcripts", id=transcript_id, org_id=org_id)
    if row is None:
        raise KeyError(transcript_id)
    return await _public_transcript(org_id=org_id, row=row, detail=True)  # type: ignore[return-value]


async def list_probes(*, org_id: str, transcript_id: str) -> list[ProbeResultPublic]:
    detail = await get_transcript(org_id=org_id, transcript_id=transcript_id)
    return detail.probes


async def create_transcript(
    *,
    org_id: str,
    user_id: str,
    candidate_id: str,
    filename: str,
    mime: str,
    content: bytes,
    source: TranscriptSource,
    max_bytes: int,
) -> TranscriptPublic:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    plan = await _current_plan_row(org_id=org_id, candidate_id=candidate_id)
    existing = await fetch_many("transcripts", org_id=org_id, candidate_id=candidate_id, order="version", desc=True, limit=1)
    version = (existing[0]["version"] if existing else 0) + 1
    transcript_id = str(uuid.uuid4())
    await insert_row(
        "transcripts",
        Transcript(
            id=transcript_id,
            org_id=org_id,
            candidate_id=candidate.id,
            job_id=candidate.job_id,
            plan_id=plan["id"] if plan else None,
            document_id=None,
            source=source.value,
            status=TranscriptStatus.uploaded.value,
            version=version,
            warnings=[],
            run_id=None,
            created_at=utcnow(),
        ),
    )
    try:
        uploaded = await store_and_extract(
            org_id=org_id,
            user_id=user_id,
            owner_type=DocumentOwnerType.transcript,
            owner_id=transcript_id,
            kind=DocumentKind.transcript,
            filename=filename,
            mime=mime,
            content=content,
            max_bytes=max_bytes,
            job_id=candidate.job_id,
            candidate_id=candidate.id,
        )
    except Exception:
        await delete_rows("transcripts", id=transcript_id, org_id=org_id)
        raise
    await update_rows("transcripts", {"document_id": uploaded.document.id}, id=transcript_id, org_id=org_id)
    row = await fetch_one("transcripts", id=transcript_id, org_id=org_id)
    assert row is not None
    return await _public_transcript(org_id=org_id, row=row)  # type: ignore[return-value]


async def start_analyze(*, org_id: str, transcript_id: str) -> PipelineRun:
    row = await fetch_one("transcripts", id=transcript_id, org_id=org_id)
    if row is None:
        raise KeyError(transcript_id)
    document = _parse(Document, await fetch_one("documents", id=row["document_id"])) if row.get("document_id") else None
    if document is None or not (document.extracted_text or "").strip():
        raise ValueError("Transcript text is not extracted yet")
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.transcript.value,
        subject_type="transcript",
        subject_id=transcript_id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await update_rows("transcripts", {"run_id": run.id, "status": TranscriptStatus.uploaded.value}, id=transcript_id)
    await enqueue_analyze(transcript_id, run.id)
    return run


async def start_analyze_unless_active(*, org_id: str, transcript_id: str) -> PipelineRun | None:
    async with _lock_for(f"analyze:{transcript_id}"):
        existing = await latest_run(
            subject_type="transcript",
            subject_id=transcript_id,
            graph=PipelineGraph.transcript.value,
        )
        if _run_pending(existing) and existing is not None:
            return existing
        try:
            return await start_analyze(org_id=org_id, transcript_id=transcript_id)
        except (KeyError, ValueError):
            return None


async def patch_transcript_turn(*, org_id: str, turn_id: str, body: TranscriptTurnPatch) -> TranscriptTurnPublic:
    row = await fetch_one("transcript_turns", id=turn_id)
    if row is None:
        raise KeyError(turn_id)
    transcript = await fetch_one("transcripts", id=row["transcript_id"], org_id=org_id)
    if transcript is None:
        raise KeyError(turn_id)
    updates: dict = {"recruiter_edited": True}
    if body.speaker is not None:
        updates["speaker"] = body.speaker.value
    if "requirement_id" in body.model_fields_set:
        req_id = body.requirement_id or None
        if req_id:
            requirement = await fetch_one("requirements", id=req_id, job_id=transcript["job_id"])
            if requirement is None:
                raise ValueError("Requirement not found")
        updates["requirement_id"] = req_id
    if "question_id" in body.model_fields_set:
        qid = body.question_id or None
        if qid:
            question = await fetch_one("planned_questions", id=qid)
            if question is None:
                raise ValueError("Question not found")
        updates["question_id"] = qid
    updated = await update_rows("transcript_turns", updates, id=turn_id)
    labels = _requirement_label_map(await list_requirements(job_id=transcript["job_id"]))
    return await _public_turn(updated[0], labels)


def _priority_value(raw) -> RequirementPriority:
    if isinstance(raw, RequirementPriority):
        return raw
    try:
        return RequirementPriority(raw)
    except ValueError:
        return RequirementPriority.unclear_priority


def _match_status(raw) -> MatchStatus:
    if isinstance(raw, MatchStatus):
        return raw
    try:
        return MatchStatus(raw)
    except ValueError:
        return MatchStatus.UNCLEAR


async def assemble_evidence_body(
    *,
    org_id: str,
    candidate_id: str,
    collected,
    transcript: dict | None,
    probes: list[dict],
    planned_requirement_ids: set[str],
    written=None,
) -> EvidenceReportBody:
    from hireflow_agents.report import CLOSING

    public = await get_candidate_public(org_id=org_id, candidate_id=candidate_id)
    if public is None:
        raise KeyError(candidate_id)
    job = await get_job_detail(org_id=org_id, job_id=public.job_id)
    if job is None:
        raise KeyError(candidate_id)
    requirements = await list_requirements(job_id=public.job_id)
    matches = await list_matches(org_id=org_id, candidate_id=candidate_id)
    labels = _requirement_label_map(requirements)
    match_by_req = {item.requirement_id: item for item in matches}
    status_by_req = {item.requirement_id: item for item in collected.statuses}
    probe_by_req = {str(item.get("requirement_id")): item for item in probes}
    partial = transcript is None
    evidence_rows: list[EvidenceItemPublic] = []
    for index, item in enumerate(collected.items, start=1):
        try:
            source = EvidenceSource(item.source)
        except ValueError:
            source = EvidenceSource.resume
        try:
            strength = EvidenceStrength(item.strength)
        except ValueError:
            strength = EvidenceStrength.none
        dims: list[EvidenceDimension] = []
        for dim in item.dimensions_supported:
            try:
                dims.append(EvidenceDimension(dim))
            except ValueError:
                continue
        evidence_rows.append(
            EvidenceItemPublic(
                id=str(uuid.uuid4()),
                code=f"E{index}",
                requirement_id=item.requirement_id,
                requirement_label=labels.get(item.requirement_id, ""),
                source=source,
                quote=scrub_internal_ids(item.quote) or "No evidence found",
                interpretation=scrub_internal_ids(item.interpretation),
                strength=strength,
                dimensions_supported=dims,
                contradicts=bool(item.contradicts_claim_id),
            )
        )
    codes_by_req: dict[str, list[str]] = {}
    for row in evidence_rows:
        codes_by_req.setdefault(row.requirement_id, []).append(row.code)

    matrix: list[RequirementAssessment] = []
    for requirement in requirements:
        match = match_by_req.get(requirement.id)
        resume_status = match.status if match else MatchStatus.MISSING
        proposed = status_by_req.get(requirement.id)
        after = _match_status(proposed.status_after_interview) if proposed and proposed.status_after_interview else None
        unvalidated = bool(proposed.unvalidated) if proposed else partial and resume_status != MatchStatus.MATCHED
        if partial:
            after = None
            final = resume_status
        else:
            final = after or resume_status
        related_evidence = [row for row in evidence_rows if row.requirement_id == requirement.id]
        strongest = next((row for row in related_evidence if row.strength == EvidenceStrength.strong), None)
        if strongest is None:
            strongest = next((row for row in related_evidence if row.quote and row.quote != "No evidence found"), None)
        matrix.append(
            RequirementAssessment(
                requirement_id=requirement.id,
                requirement_label=requirement.normalized_label or requirement.text,
                priority=_priority_value(requirement.priority),
                status_after_resume=resume_status,
                status_after_interview=after,
                final=final,
                unvalidated=unvalidated,
                strongest_quote=strongest.quote if strongest else "No evidence found",
                source=strongest.source if strongest else None,
                remaining_doubt=scrub_internal_ids(proposed.remaining_doubt if proposed else ""),
                evidence_codes=codes_by_req.get(requirement.id, []),
            )
        )

    must_haves = [row for row in matrix if row.priority == RequirementPriority.must_have]
    unresolved: list[UnresolvedGap] = []
    for row in matrix:
        probe = probe_by_req.get(row.requirement_id)
        followups = [scrub_internal_ids(item) for item in (probe or {}).get("remaining_followups") or [] if item]
        if followups or row.unvalidated or (row.final != MatchStatus.MATCHED and (probe or partial)):
            verdict = None
            if probe and probe.get("verdict"):
                try:
                    verdict = ProbeVerdict(probe["verdict"])
                except ValueError:
                    verdict = None
            unresolved.append(
                UnresolvedGap(
                    requirement_id=row.requirement_id,
                    requirement_label=row.requirement_label,
                    verdict=verdict,
                    followups=followups,
                    note=row.remaining_doubt,
                )
            )
    contradictions = [
        ContradictionRow(
            requirement_label=row.requirement_label,
            quote=row.quote,
            interpretation=row.interpretation,
            evidence_code=row.code,
        )
        for row in evidence_rows
        if row.contradicts
    ]
    coverage = []
    for req in requirements:
        verdict = None
        probe = probe_by_req.get(req.id)
        if probe and probe.get("verdict"):
            try:
                verdict = ProbeVerdict(probe["verdict"])
            except ValueError:
                verdict = None
        coverage.append(
            CoverageRow(
                requirement_id=req.id,
                requirement_label=req.normalized_label or req.text,
                verdict=verdict,
                skipped_in_plan=bool(planned_requirement_ids) and req.id not in planned_requirement_ids,
            )
        )
    overall_resume = public.overall_match
    interview_items = [
        (row.final, row.priority)
        for row in matrix
        if not partial
    ]
    overall_interview = score_overall_match(interview_items) if interview_items else None
    headline = ""
    risks: list[str] = []
    closing = CLOSING
    if written is not None:
        headline = scrub_internal_ids(written.headline)
        risks = [scrub_internal_ids(item) for item in written.remaining_risks if item]
        closing = CLOSING
    return EvidenceReportBody(
        partial=partial,
        headline=headline,
        generated_at=utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        transcript_id=transcript["id"] if transcript else None,
        transcript_version=transcript.get("version") if transcript else None,
        overall_after_resume=overall_resume,
        overall_after_interview=overall_interview,
        matrix=matrix,
        must_haves=must_haves,
        unresolved=unresolved,
        contradictions=contradictions,
        coverage=coverage,
        remaining_risks=risks,
        closing=closing,
        evidence=evidence_rows,
    )


def evidence_report_markdown(*, candidate_name: str, job_title: str, body: EvidenceReportBody) -> str:
    lines = [
        f"# Candidate evidence report: {candidate_name} — {job_title}",
        "",
        f"Generated: {body.generated_at}",
        f"Report type: {'partial (resume only)' if body.partial else 'resume + transcript'}",
    ]
    if body.transcript_version:
        lines.append(f"Transcript version: {body.transcript_version}")
    resume_fit = body.overall_after_resume.value.replace("_", " ").title() + " match" if body.overall_after_resume else "not scored"
    interview_fit = (
        body.overall_after_interview.value.replace("_", " ").title() + " match"
        if body.overall_after_interview
        else ("empty" if body.partial else "not scored")
    )
    lines.extend(["", f"Overall after resume: {resume_fit}", f"Overall after interview: {interview_fit}", ""])
    if body.headline:
        lines.extend([body.headline.strip(), ""])
    lines.extend(
        [
            body.closing,
            "",
            "## Matrix",
            "",
            "| Requirement | Resume | Interview | Final | Evidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in body.matrix:
        interview = row.status_after_interview.value if row.status_after_interview else ("—" if body.partial else "unchanged")
        codes = ", ".join(row.evidence_codes) or "—"
        flag = " (unvalidated)" if row.unvalidated else ""
        lines.append(
            f"| {row.requirement_label} | {row.status_after_resume.value} | {interview}{flag} | {row.final.value} | {codes} |"
        )
    lines.extend(["", "## Must-haves", ""])
    if not body.must_haves:
        lines.append("No must-have requirements.")
        lines.append("")
    for row in body.must_haves:
        source = row.source.value if row.source else "none"
        lines.append(f"### {row.requirement_label} — {row.final.value}")
        lines.append("")
        lines.append(f"Strongest quote ({source}): {row.strongest_quote or 'No evidence found'}")
        lines.append("")
        if row.evidence_codes:
            lines.append("Cited evidence: " + ", ".join(row.evidence_codes))
            lines.append("")
        if row.remaining_doubt:
            lines.append(row.remaining_doubt)
            lines.append("")
    lines.extend(["## Unresolved gaps and remaining follow-ups", ""])
    if not body.unresolved:
        lines.append("No unresolved gaps.")
        lines.append("")
    for row in body.unresolved:
        verdict = row.verdict.value.replace("_", " ") if row.verdict else "unvalidated"
        lines.append(f"### {row.requirement_label} — {verdict}")
        lines.append("")
        if row.note:
            lines.append(row.note)
            lines.append("")
        for question in row.followups:
            lines.append(f"- {question}")
        if row.followups:
            lines.append("")
    lines.extend(["## Contradictions", ""])
    if not body.contradictions:
        lines.append("None recorded.")
        lines.append("")
    for row in body.contradictions:
        lines.append(f"- {row.evidence_code} {row.requirement_label}: {row.quote}")
        if row.interpretation:
            lines.append(f"  {row.interpretation}")
        lines.append("")
    lines.extend(["## Transcript coverage", ""])
    if body.partial:
        lines.append("No transcript. Interview coverage is empty.")
        lines.append("")
    else:
        for row in body.coverage:
            verdict = row.verdict.value.replace("_", " ") if row.verdict else "not scored"
            skipped = " (not in plan)" if row.skipped_in_plan else ""
            lines.append(f"- {row.requirement_label}: {verdict}{skipped}")
        lines.append("")
    lines.extend(["## Remaining risks", ""])
    if not body.remaining_risks:
        lines.append("No outstanding evidence risks were recorded. The recruiter still decides.")
        lines.append("")
    for risk in body.remaining_risks:
        lines.append(f"- {risk}")
    lines.extend(["", "## Evidence index", ""])
    for item in body.evidence:
        lines.append(f"- {item.code} ({item.source.value}, {item.strength.value}) {item.requirement_label}: {item.quote}")
    lines.extend(["", body.closing, ""])
    return "\n".join(lines)


async def persist_evidence_report(
    *,
    org_id: str,
    candidate_id: str,
    run_id: str,
    collected,
    transcript: dict | None,
    probes: list[dict],
    planned_requirement_ids: set[str],
    written=None,
    replace_report_id: str | None = None,
) -> Report:
    public = await get_candidate_public(org_id=org_id, candidate_id=candidate_id)
    if public is None:
        raise KeyError(candidate_id)
    job = await get_job_detail(org_id=org_id, job_id=public.job_id)
    if job is None:
        raise KeyError(candidate_id)
    body = await assemble_evidence_body(
        org_id=org_id,
        candidate_id=candidate_id,
        collected=collected,
        transcript=transcript,
        probes=probes,
        planned_requirement_ids=planned_requirement_ids,
        written=written,
    )
    for item in collected.statuses:
        await update_rows(
            "match_results",
            {"status_after_interview": item.status_after_interview},
            candidate_id=candidate_id,
            requirement_id=item.requirement_id,
            org_id=org_id,
        )
    markdown = evidence_report_markdown(candidate_name=public.full_name, job_title=job.title, body=body)
    content = markdown.encode("utf-8")
    plan_id = transcript.get("plan_id") if transcript else None
    if replace_report_id:
        existing = await fetch_one("reports", id=replace_report_id, org_id=org_id)
        if existing is None:
            replace_report_id = None
    if replace_report_id:
        report_id = replace_report_id
        version = existing["version"]
        filename = existing["original_filename"]
        key = existing["storage_key"]
    else:
        previous = [
            row
            for row in await fetch_many("reports", org_id=org_id, candidate_id=candidate_id, order="version", desc=True)
            if row.get("kind") == ReportKind.evidence.value
        ]
        version = (previous[0]["version"] if previous else 0) + 1
        report_id = str(uuid.uuid4())
        filename = f"{_safe_filename(public.full_name)}-{_safe_filename(job.title)}-evidence-v{version}.md"
        key = f"org/{org_id}/jobs/{job.id}/candidates/{public.id}/reports/{report_id}/evidence.md"
    await get_store().put(key, content, "text/markdown")
    payload = {
        "storage_key": key,
        "original_filename": filename,
        "mime": "text/markdown",
        "body": body.model_dump(mode="json"),
        "generated_from_run_id": run_id,
        "plan_id": plan_id,
    }
    if replace_report_id:
        await update_rows("reports", payload, id=report_id, org_id=org_id)
        await delete_rows("evidence_items", report_id=report_id)
        report = Report.model_validate(await fetch_one("reports", id=report_id, org_id=org_id))
    else:
        report = Report(
            id=report_id,
            org_id=org_id,
            candidate_id=candidate_id,
            job_id=public.job_id,
            plan_id=plan_id,
            kind=ReportKind.evidence.value,
            version=version,
            storage_key=key,
            original_filename=filename,
            mime="text/markdown",
            body=body.model_dump(mode="json"),
            generated_from_run_id=run_id,
            created_at=utcnow(),
        )
        report = Report.model_validate(await insert_row("reports", report))
    item_rows = []
    collected_by_index = list(collected.items)
    for public_item, raw in zip(body.evidence, collected_by_index, strict=False):
        item_rows.append(
            {
                "id": public_item.id,
                "org_id": org_id,
                "candidate_id": candidate_id,
                "report_id": report.id,
                "requirement_id": public_item.requirement_id,
                "source": public_item.source.value,
                "quote": public_item.quote,
                "source_ref": raw.source_ref,
                "interpretation": public_item.interpretation,
                "strength": public_item.strength.value,
                "dimensions_supported": [item.value for item in public_item.dimensions_supported],
                "contradicts_claim_id": raw.contradicts_claim_id,
            }
        )
    await insert_rows("evidence_items", item_rows)
    return report


async def _latest_evidence_report_row(*, org_id: str, candidate_id: str) -> dict | None:
    rows = await fetch_many("reports", org_id=org_id, candidate_id=candidate_id, order="created_at", desc=True)
    for row in rows:
        if row.get("kind") == ReportKind.evidence.value:
            return row
    return None


async def get_evidence_report(*, org_id: str, candidate_id: str) -> EvidenceReportResponse:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    run = await latest_run(subject_type="report", subject_id=candidate_id, graph=PipelineGraph.report.value)
    row = await _latest_evidence_report_row(org_id=org_id, candidate_id=candidate_id)
    if row is None:
        return EvidenceReportResponse(report=None, body=None, decision=None, run=_public_run(run))
    report = Report.model_validate(row)
    body = None
    if report.body:
        try:
            body = EvidenceReportBody.model_validate(report.body)
        except Exception:
            body = None
    decision_row = await fetch_one("decisions", report_id=report.id, org_id=org_id)
    decision = None
    if decision_row:
        item = Decision.model_validate(decision_row)
        decision = DecisionPublic(
            id=item.id,
            report_id=item.report_id,
            outcome=item.outcome,  # type: ignore[arg-type]
            notes=item.notes,
            decided_by=item.decided_by,
            decided_at=item.decided_at,
        )
    return EvidenceReportResponse(
        report=_public_report(report),
        body=body,
        decision=decision,
        run=_public_run(run),
    )


async def start_report(*, org_id: str, candidate_id: str) -> PipelineRun:
    candidate = _parse(Candidate, await fetch_one("candidates", id=candidate_id, org_id=org_id))
    if candidate is None:
        raise KeyError(candidate_id)
    matches = await fetch_many("match_results", candidate_id=candidate_id, limit=1)
    if not matches:
        raise ValueError("Match the resume to the JD before generating an evidence report")
    run = PipelineRun(
        id=str(uuid.uuid4()),
        org_id=org_id,
        graph=PipelineGraph.report.value,
        subject_type="report",
        subject_id=candidate_id,
        status=PipelineStatus.queued.value,
        error=None,
        trace_id=str(uuid.uuid4()),
        created_at=utcnow(),
    )
    run = PipelineRun.model_validate(await insert_row("pipeline_runs", run))
    await enqueue_report(candidate_id, run.id)
    return run


async def start_report_unless_active(*, org_id: str, candidate_id: str) -> PipelineRun | None:
    async with _lock_for(f"report:{candidate_id}"):
        existing = await latest_run(subject_type="report", subject_id=candidate_id, graph=PipelineGraph.report.value)
        if _run_pending(existing) and existing is not None:
            return existing
        try:
            return await start_report(org_id=org_id, candidate_id=candidate_id)
        except (KeyError, ValueError):
            return None


async def record_decision(*, org_id: str, user_id: str, report_id: str, body: DecisionCreate) -> DecisionPublic:
    row = await fetch_one("reports", id=report_id, org_id=org_id)
    if row is None:
        raise KeyError(report_id)
    if row.get("kind") != ReportKind.evidence.value:
        raise ValueError("Decisions attach only to evidence reports")
    existing = await fetch_one("decisions", report_id=report_id, org_id=org_id)
    payload = {
        "outcome": body.outcome.value,
        "notes": (body.notes or "").strip(),
        "decided_by": user_id,
        "decided_at": utcnow(),
    }
    if existing:
        updated = await update_rows("decisions", payload, id=existing["id"], org_id=org_id)
        item = Decision.model_validate(updated[0])
    else:
        item = Decision.model_validate(
            await insert_row(
                "decisions",
                Decision(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    report_id=report_id,
                    outcome=body.outcome.value,
                    notes=(body.notes or "").strip(),
                    decided_by=user_id,
                    decided_at=payload["decided_at"],
                ),
            )
        )
    return DecisionPublic(
        id=item.id,
        report_id=item.report_id,
        outcome=item.outcome,  # type: ignore[arg-type]
        notes=item.notes,
        decided_by=item.decided_by,
        decided_at=item.decided_at,
    )
