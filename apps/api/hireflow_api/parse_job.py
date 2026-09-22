from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from hireflow_agents.experience import resolve_years_experience
from hireflow_agents.graphs.screening import run_jd_parse, run_resume_parse
from hireflow_agents.llm import LLMError
from hireflow_agents.resume_parser import ParsedClaim
from hireflow_domain.enums import ClaimKind
from hireflow_api.db import delete_rows, fetch_one, insert_row, insert_rows, update_rows
from hireflow_api.config import settings
from hireflow_api.llm import parser_llm_config
from hireflow_api.models import AgentTrace, Candidate, Job, PipelineRun, utcnow
from hireflow_api.services import latest_document

logger = logging.getLogger(__name__)


async def parse_job(kind: str, subject_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    if run_row is None:
        logger.error("parse job missing run %s", run_id)
        return
    run = PipelineRun.model_validate(run_row)
    await update_rows("pipeline_runs", {"status": "running", "started_at": utcnow()}, id=run.id)

    if not settings.llm_configured:
        await update_rows(
            "pipeline_runs",
            {
                "status": "failed",
                "error": "GROQ_API_KEY is not configured. Add it to .env and restart the API.",
                "finished_at": utcnow(),
            },
            id=run.id,
        )
        return

    started = time.perf_counter()
    input_payload: dict = {"kind": kind, "subject_id": subject_id}
    output_payload: dict = {}
    model = parser_llm_config().model
    prompt_version = "jd_parser.v1" if kind == "jd" else "resume_parser.v2"
    status = "succeeded"
    error = None
    try:
        if kind == "jd":
            output_payload = await _parse_jd(run, subject_id)
        elif kind == "resume":
            output_payload = await _parse_resume(run, subject_id)
        else:
            raise ValueError(f"unknown parse kind {kind}")
    except LLMError as exc:
        logger.exception("parse failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("parse failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}

    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    await insert_row(
        "agent_traces",
        AgentTrace(
            id=str(uuid.uuid4()),
            org_id=run.org_id,
            run_id=run.id,
            agent="jd_parser" if kind == "jd" else "resume_parser",
            schema_version="1.0",
            model=model,
            prompt_version=prompt_version,
            input_hash=hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest(),
            input_json=input_payload,
            output_json=output_payload,
            token_usage=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
    if status == "succeeded":
        from hireflow_api.services import continue_after_parse

        await continue_after_parse(org_id=run.org_id, kind=kind, subject_id=subject_id)


async def _parse_jd(run: PipelineRun, job_id: str) -> dict:
    job_row = await fetch_one("jobs", id=job_id)
    if job_row is None:
        raise ValueError("Job not found")
    job = Job.model_validate(job_row)
    if job.org_id != run.org_id:
        raise ValueError("Job not found")
    document = await latest_document(owner_type="job", owner_id=job_id, kind="jd")
    if document is None or not (document.extracted_text or "").strip():
        raise ValueError("JD text is not extracted yet")

    parsed = await run_jd_parse(
        document.extracted_text or "",
        parser_llm_config(),
        filename=document.original_filename,
    )
    await delete_rows("requirements", job_id=job_id)
    rows = []
    for index, item in enumerate(parsed.requirements):
        span = item.source_span.model_dump()
        if not span.get("quote"):
            span["quote"] = item.source_quote
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "org_id": job.org_id,
                "job_id": job.id,
                "document_version": document.version,
                "text": item.text.strip(),
                "normalized_label": item.normalized_label.strip() or item.text.strip()[:80],
                "category": item.category.value,
                "priority": item.priority.value,
                "source_quote": item.source_quote.strip(),
                "source_span": span,
                "recruiter_edited": False,
                "sort_order": index,
            }
        )
    await insert_rows("requirements", rows)
    return {
        "ok": True,
        "count": len(parsed.requirements),
        "warnings": parsed.warnings,
    }


async def _parse_resume(run: PipelineRun, candidate_id: str) -> dict:
    candidate_row = await fetch_one("candidates", id=candidate_id)
    if candidate_row is None:
        raise ValueError("Candidate not found")
    candidate = Candidate.model_validate(candidate_row)
    if candidate.org_id != run.org_id:
        raise ValueError("Candidate not found")
    document = await latest_document(owner_type="candidate", owner_id=candidate_id, kind="resume")
    if document is None or not (document.extracted_text or "").strip():
        raise ValueError("Resume text is not extracted yet")

    resume_text = document.extracted_text or ""
    parsed = await run_resume_parse(
        resume_text,
        parser_llm_config(),
        filename=document.original_filename,
    )
    profile = parsed.profile
    claim_texts = [f"{item.text} {item.quote}" for item in profile.claims]
    resolved_years = resolve_years_experience(
        summary=profile.summary,
        resume_text=resume_text,
        claim_texts=claim_texts,
        current=profile.years_experience,
    )
    if resolved_years is not None:
        profile.years_experience = resolved_years
    has_total_years_claim = any(
        item.kind.value == "years_claim"
        and (
            "experience" in (item.skill_label or "").lower()
            or "experience" in item.text.lower()
        )
        for item in profile.claims
    )
    if resolved_years is not None and not has_total_years_claim:
        profile.claims.append(
            ParsedClaim(
                kind=ClaimKind.years_claim,
                text=f"{resolved_years} years of professional experience",
                skill_label="Professional experience",
                years=resolved_years,
                quote=profile.summary or f"{resolved_years} years of experience",
            )
        )
    await delete_rows("claims", candidate_id=candidate_id)
    await delete_rows("profiles", candidate_id=candidate_id)
    await insert_row(
        "profiles",
        {
            "id": str(uuid.uuid4()),
            "org_id": candidate.org_id,
            "candidate_id": candidate.id,
            "full_name": profile.full_name,
            "email": profile.email,
            "summary": profile.summary,
            "years_experience": profile.years_experience,
            "education": profile.education,
            "roles": profile.roles,
            "skills_listed": profile.skills_listed,
            "parser_warnings": list(profile.parser_warnings) + list(parsed.warnings),
        },
    )
    years_claims = 0
    claim_rows = []
    for item in profile.claims:
        if item.kind.value == "years_claim":
            years_claims += 1
        span = item.source_span.model_dump()
        if not span.get("quote"):
            span["quote"] = item.quote
        claim_rows.append(
            {
                "id": str(uuid.uuid4()),
                "org_id": candidate.org_id,
                "candidate_id": candidate.id,
                "kind": item.kind.value,
                "text": item.text.strip(),
                "skill_label": item.skill_label,
                "years": item.years,
                "source_span": span,
                "quote": item.quote.strip() or item.text.strip(),
            }
        )
    await insert_rows("claims", claim_rows)
    return {
        "ok": True,
        "claim_count": len(profile.claims),
        "years_claims": years_claims,
        "warnings": parsed.warnings,
    }
