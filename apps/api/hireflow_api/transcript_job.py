from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from hireflow_agents.graphs.transcript import run_probe, run_transcript_parse
from hireflow_agents.llm import LLMError
from hireflow_api.db import delete_rows, fetch_many, fetch_one, insert_row, insert_rows, update_rows
from hireflow_api.llm import agent_llm_config
from hireflow_api.models import AgentTrace, Candidate, PipelineRun, utcnow
from hireflow_domain.enums import RequirementPriority, TranscriptStatus

logger = logging.getLogger(__name__)


async def analyze_transcript_job(transcript_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    transcript_row = await fetch_one("transcripts", id=transcript_id)
    if run_row is None or transcript_row is None:
        logger.error("transcript job missing run or transcript: %s %s", run_id, transcript_id)
        return

    run = PipelineRun.model_validate(run_row)
    await update_rows("pipeline_runs", {"status": "running", "started_at": utcnow()}, id=run.id)
    await update_rows("transcripts", {"status": TranscriptStatus.uploaded.value, "run_id": run.id}, id=transcript_id)

    started = time.perf_counter()
    input_payload = {"transcript_id": transcript_id}
    output_payload: dict = {}
    error = None
    status = "succeeded"
    try:
        output_payload = await _run_analyze(run, transcript_row)
        await update_rows(
            "transcripts",
            {"status": TranscriptStatus.analyzed.value, "warnings": output_payload.get("warnings") or []},
            id=transcript_id,
        )
    except LLMError as exc:
        logger.exception("transcript analyze failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
        await update_rows("transcripts", {"status": TranscriptStatus.failed.value}, id=transcript_id)
    except Exception as exc:
        logger.exception("transcript analyze failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
        await update_rows("transcripts", {"status": TranscriptStatus.failed.value}, id=transcript_id)

    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    for agent, prompt_version in (("transcript_parser", "transcript_parser.v1"), ("prober", "prober.v1")):
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

    if status == "succeeded":
        try:
            from hireflow_api.services import start_report_unless_active

            await start_report_unless_active(org_id=run.org_id, candidate_id=transcript_row["candidate_id"])
        except Exception:
            logger.exception("could not enqueue evidence report")


async def _run_analyze(run: PipelineRun, transcript_row: dict) -> dict:
    from hireflow_api.services import list_requirements, scrub_internal_ids

    candidate_row = await fetch_one("candidates", id=transcript_row["candidate_id"], org_id=run.org_id)
    if candidate_row is None:
        raise ValueError("Candidate not found")
    candidate = Candidate.model_validate(candidate_row)
    document_id = transcript_row.get("document_id")
    document_row = await fetch_one("documents", id=document_id) if document_id else None
    text = ((document_row or {}).get("extracted_text") or "").strip()
    if not text:
        raise ValueError("Transcript text is not extracted yet")

    requirements = await list_requirements(job_id=candidate.job_id)
    req_payload = [
        {
            "id": item.id,
            "label": item.normalized_label or item.text,
            "priority": item.priority.value if hasattr(item.priority, "value") else item.priority,
        }
        for item in requirements
    ]
    plan_id = transcript_row.get("plan_id")
    question_rows = await fetch_many("planned_questions", plan_id=plan_id, order="sort_order") if plan_id else []
    questions = [
        {
            "id": row["id"],
            "requirement_id": row["requirement_id"],
            "prompt": row["prompt"],
            "evidence_target": row.get("evidence_target") or [],
        }
        for row in question_rows
        if not row.get("dropped")
    ]

    parsed = await run_transcript_parse(
        text,
        agent_llm_config("transcript_parser"),
        candidate_name=candidate.full_name,
        requirements=req_payload,
        questions=questions,
    )
    await delete_rows("probe_results", transcript_id=transcript_row["id"])
    await delete_rows("transcript_turns", transcript_id=transcript_row["id"])
    turn_rows = []
    for index, turn in enumerate(parsed.turns):
        turn_rows.append(
            {
                "id": str(uuid.uuid4()),
                "org_id": run.org_id,
                "transcript_id": transcript_row["id"],
                "speaker": turn.speaker,
                "text": scrub_internal_ids(turn.text) or turn.text.strip(),
                "char_start": turn.char_start,
                "char_end": turn.char_end,
                "requirement_id": turn.requirement_id,
                "question_id": turn.planned_question_id,
                "sort_order": index,
                "recruiter_edited": False,
            }
        )
    await insert_rows("transcript_turns", turn_rows)
    await update_rows(
        "transcripts",
        {"status": TranscriptStatus.parsed.value, "warnings": parsed.warnings},
        id=transcript_row["id"],
    )

    probe_requirements = _probe_targets(req_payload, questions, turn_rows)
    probed = await run_probe(
        requirements=probe_requirements,
        turns=[
            {
                "id": row["id"],
                "speaker": row["speaker"],
                "text": row["text"],
                "requirement_id": row["requirement_id"],
            }
            for row in turn_rows
        ],
        config=agent_llm_config("prober"),
    )
    probe_rows = [
        {
            "id": str(uuid.uuid4()),
            "org_id": run.org_id,
            "transcript_id": transcript_row["id"],
            "requirement_id": item.requirement_id,
            "verdict": item.verdict,
            "missing_dimensions": item.missing_dimensions,
            "supporting_turn_ids": item.supporting_turn_ids,
            "remaining_followups": [scrub_internal_ids(line) for line in item.remaining_followups],
            "rationale": scrub_internal_ids(item.rationale),
        }
        for item in probed.results
    ]
    await insert_rows("probe_results", probe_rows)
    warnings = list(parsed.warnings)
    for warning in probed.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return {
        "ok": True,
        "warnings": warnings,
        "transcript_parser": {"count": len(turn_rows), "warnings": parsed.warnings},
        "prober": {"count": len(probe_rows), "warnings": probed.warnings},
    }


def _probe_targets(requirements: list[dict], questions: list[dict], turns: list[dict]) -> list[dict]:
    by_id = {item["id"]: item for item in requirements}
    selected: dict[str, dict] = {}
    for question in questions:
        req = by_id.get(question["requirement_id"])
        if req is None:
            continue
        item = dict(req)
        item["evidence_target"] = question.get("evidence_target") or []
        selected[req["id"]] = item
    for req in requirements:
        if req.get("priority") == RequirementPriority.must_have.value:
            selected.setdefault(req["id"], dict(req))
    for turn in turns:
        req_id = turn.get("requirement_id")
        if req_id and req_id in by_id:
            selected.setdefault(req_id, dict(by_id[req_id]))
    return list(selected.values())
