from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from hireflow_agents.graphs.report import run_collect_evidence, run_write_report
from hireflow_agents.llm import LLMError
from hireflow_api.db import fetch_many, fetch_one, insert_row, update_rows
from hireflow_api.llm import agent_llm_config
from hireflow_api.models import AgentTrace, Candidate, PipelineRun, utcnow
from hireflow_domain.enums import TranscriptStatus

logger = logging.getLogger(__name__)


async def generate_report_job(candidate_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    if run_row is None:
        logger.error("report job missing run %s", run_id)
        return
    run = PipelineRun.model_validate(run_row)
    await update_rows("pipeline_runs", {"status": "running", "started_at": utcnow()}, id=run.id)

    started = time.perf_counter()
    input_payload = {"candidate_id": candidate_id}
    output_payload: dict = {}
    error = None
    status = "succeeded"
    try:
        output_payload = await _run_report(run, candidate_id)
    except LLMError as exc:
        logger.exception("evidence report failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("evidence report failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}

    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    for agent, prompt_version in (("evidence_collector", "evidence_collector.v1"), ("report", "report.v1")):
        await insert_row(
            "agent_traces",
            AgentTrace(
                id=str(uuid.uuid4()),
                org_id=run.org_id,
                run_id=run.id,
                agent=agent,
                schema_version="1.0",
                model=agent_llm_config(agent).model,
                prompt_version=prompt_version,
                input_hash=hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest(),
                input_json=input_payload,
                output_json=output_payload.get(agent, output_payload),
                token_usage=None,
                latency_ms=latency_ms,
            ),
        )


async def _run_report(run: PipelineRun, candidate_id: str) -> dict:
    from hireflow_api.services import (
        assemble_evidence_body,
        get_candidate_public,
        get_job_detail,
        list_matches,
        list_requirements,
        persist_evidence_report,
        scrub_internal_ids,
    )

    public = await get_candidate_public(org_id=run.org_id, candidate_id=candidate_id)
    if public is None:
        raise ValueError("Candidate not found")
    job = await get_job_detail(org_id=run.org_id, job_id=public.job_id)
    if job is None:
        raise ValueError("Job not found")
    matches = await list_matches(org_id=run.org_id, candidate_id=candidate_id)
    if not matches:
        raise ValueError("Match the resume to the JD before generating an evidence report")
    requirements = await list_requirements(job_id=public.job_id)
    claims = await fetch_many("claims", candidate_id=candidate_id)
    transcript = await _latest_analyzed_transcript(run.org_id, candidate_id)
    probes: list[dict] = []
    turns: list[dict] = []
    if transcript:
        probes = await fetch_many("probe_results", transcript_id=transcript["id"])
        turns = await fetch_many("transcript_turns", transcript_id=transcript["id"], order="sort_order")

    req_payload = [
        {
            "id": item.id,
            "label": item.normalized_label or item.text,
            "priority": item.priority.value if hasattr(item.priority, "value") else item.priority,
        }
        for item in requirements
    ]
    match_payload = [
        {
            "requirement_id": item.requirement_id,
            "status": item.status.value,
            "dimension_flags": item.dimension_flags.model_dump(),
            "supporting_claim_ids": list(item.supporting_claim_ids or []),
            "quotes": list(item.quotes or []),
            "rationale": item.rationale,
        }
        for item in matches
    ]
    claim_payload = [
        {
            "id": row["id"],
            "kind": row.get("kind"),
            "text": row.get("text"),
            "quote": row.get("quote"),
            "skill_label": row.get("skill_label"),
        }
        for row in claims
    ]
    probe_payload = [
        {
            "requirement_id": row["requirement_id"],
            "verdict": row.get("verdict"),
            "missing_dimensions": row.get("missing_dimensions") or [],
            "supporting_turn_ids": row.get("supporting_turn_ids") or [],
            "remaining_followups": [scrub_internal_ids(item) for item in (row.get("remaining_followups") or [])],
            "rationale": scrub_internal_ids(row.get("rationale")),
        }
        for row in probes
    ]
    turn_payload = [
        {
            "id": row["id"],
            "speaker": row.get("speaker"),
            "text": row.get("text"),
            "requirement_id": row.get("requirement_id"),
        }
        for row in turns
    ]

    collected = await run_collect_evidence(
        requirements=req_payload,
        matches=match_payload,
        claims=claim_payload,
        probes=probe_payload,
        turns=turn_payload,
        config=agent_llm_config("evidence_collector"),
    )
    for item in collected.items:
        item.interpretation = scrub_internal_ids(item.interpretation)
        item.quote = scrub_internal_ids(item.quote) or item.quote

    plan = await fetch_one("interview_plans", id=transcript["plan_id"]) if transcript and transcript.get("plan_id") else None
    planned_ids: set[str] = set()
    if plan:
        planned_ids = {
            row["requirement_id"]
            for row in await fetch_many("planned_questions", plan_id=plan["id"])
            if not row.get("dropped")
        }

    body = await assemble_evidence_body(
        org_id=run.org_id,
        candidate_id=candidate_id,
        collected=collected,
        transcript=transcript,
        probes=probe_payload,
        planned_requirement_ids=planned_ids,
        written=None,
    )
    written = await run_write_report(
        candidate_name=public.full_name,
        job_title=job.title,
        partial=body.partial,
        matrix=[row.model_dump(mode="json") for row in body.matrix],
        evidence=[row.model_dump(mode="json") for row in body.evidence],
        unresolved=[row.model_dump(mode="json") for row in body.unresolved],
        contradictions=[row.model_dump(mode="json") for row in body.contradictions],
        config=agent_llm_config("report"),
    )
    report = await persist_evidence_report(
        org_id=run.org_id,
        candidate_id=candidate_id,
        run_id=run.id,
        collected=collected,
        transcript=transcript,
        probes=probe_payload,
        planned_requirement_ids=planned_ids,
        written=written,
    )
    return {
        "ok": True,
        "evidence_collector": {
            "count": len(collected.items),
            "warnings": collected.warnings,
            "statuses": [item.model_dump() for item in collected.statuses],
        },
        "report": {
            "report_id": report.id,
            "headline": written.headline,
            "warnings": written.warnings,
        },
    }


async def _latest_analyzed_transcript(org_id: str, candidate_id: str) -> dict | None:
    rows = await fetch_many("transcripts", org_id=org_id, candidate_id=candidate_id, order="version", desc=True)
    for row in rows:
        if row.get("status") == TranscriptStatus.analyzed.value:
            return row
    return None
