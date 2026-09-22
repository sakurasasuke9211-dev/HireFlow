from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from hireflow_agents.graphs.screening import run_interview_plan
from hireflow_agents.llm import LLMError
from hireflow_api.db import fetch_many, fetch_one, insert_row, insert_rows, update_rows
from hireflow_api.llm import agent_llm_config
from hireflow_api.models import AgentTrace, Candidate, PipelineRun, utcnow
from hireflow_domain.enums import InterviewPlanStatus

logger = logging.getLogger(__name__)


async def design_plan_job(candidate_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    if run_row is None:
        logger.error("plan job missing run %s", run_id)
        return
    run = PipelineRun.model_validate(run_row)
    await update_rows("pipeline_runs", {"status": "running", "started_at": utcnow()}, id=run.id)

    started = time.perf_counter()
    input_payload = {"candidate_id": candidate_id}
    output_payload: dict = {}
    error = None
    status = "succeeded"
    try:
        output_payload = await _run_plan(run, candidate_id)
    except LLMError as exc:
        logger.exception("interview plan failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("interview plan failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}

    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    await insert_row(
        "agent_traces",
        AgentTrace(
            id=str(uuid.uuid4()),
            org_id=run.org_id,
            run_id=run.id,
            agent="interview_designer",
            schema_version="1.0",
            model=agent_llm_config("interview_designer").model,
            prompt_version="interview_designer.v1",
            input_hash=hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest(),
            input_json=input_payload,
            output_json=output_payload.get("interview_designer", output_payload),
            token_usage=None,
            latency_ms=latency_ms,
        ),
    )


async def _run_plan(run: PipelineRun, candidate_id: str) -> dict:
    from hireflow_api.services import list_gaps, list_matches, persist_interview_plan, scrub_internal_ids

    candidate_row = await fetch_one("candidates", id=candidate_id)
    if candidate_row is None:
        raise ValueError("Candidate not found")
    candidate = Candidate.model_validate(candidate_row)
    if candidate.org_id != run.org_id:
        raise ValueError("Candidate not found")

    matches = await list_matches(org_id=run.org_id, candidate_id=candidate_id)
    if not matches:
        raise ValueError("Match the resume to the JD before generating an interview plan")
    gaps = await list_gaps(org_id=run.org_id, candidate_id=candidate_id)
    profile_row = await fetch_one("profiles", candidate_id=candidate.id)
    profile = None
    if profile_row:
        profile = {
            "full_name": profile_row.get("full_name"),
            "summary": profile_row.get("summary"),
            "roles": profile_row.get("roles") or [],
            "skills_listed": profile_row.get("skills_listed") or [],
        }

    match_by_req = {item.requirement_id: item for item in matches}
    gap_payload: list[dict] = []
    for gap in gaps:
        if gap.skip_probe:
            continue
        match = match_by_req.get(gap.requirement_id)
        quote = match.quotes[0] if match and match.quotes else None
        flags = match.dimension_flags.model_dump() if match else {}
        gap_payload.append(
            {
                "requirement_id": gap.requirement_id,
                "label": gap.requirement_label,
                "status": gap.status.value if gap.status else "UNCLEAR",
                "priority": match.requirement_priority.value if match and match.requirement_priority else "must_have",
                "severity": gap.severity.value,
                "goal": gap.investigation_goal,
                "themes": list(gap.suggested_probe_themes or []),
                "quote": quote,
                "dimension_flags": flags,
                "sort_order": 0,
            }
        )

    designed = await run_interview_plan(
        gaps=gap_payload,
        profile=profile,
        config=agent_llm_config("interview_designer"),
    )
    questions = []
    for index, item in enumerate(designed.questions):
        questions.append(
            {
                "requirement_id": item.requirement_id,
                "sort_order": index,
                "prompt": scrub_internal_ids(item.prompt),
                "planned_followups": [scrub_internal_ids(line) for line in item.planned_followups],
                "evidence_target": list(item.evidence_target),
            }
        )

    existing = await fetch_many("interview_plans", candidate_id=candidate.id, order="version", desc=True)
    version = (existing[0]["version"] if existing else 0) + 1
    for row in existing:
        if row["status"] != InterviewPlanStatus.superseded.value:
            await update_rows(
                "interview_plans",
                {"status": InterviewPlanStatus.superseded.value},
                id=row["id"],
                org_id=run.org_id,
            )

    plan_id = str(uuid.uuid4())
    await insert_row(
        "interview_plans",
        {
            "id": plan_id,
            "org_id": candidate.org_id,
            "candidate_id": candidate.id,
            "job_id": candidate.job_id,
            "status": InterviewPlanStatus.draft.value,
            "version": version,
            "brief_report_id": None,
            "run_id": run.id,
            "created_at": utcnow(),
        },
    )
    question_rows = [
        {
            "id": str(uuid.uuid4()),
            "org_id": candidate.org_id,
            "plan_id": plan_id,
            "requirement_id": item["requirement_id"],
            "sort_order": item["sort_order"],
            "prompt": item["prompt"],
            "planned_followups": item["planned_followups"],
            "evidence_target": item["evidence_target"],
            "source": "generated",
            "dropped": False,
        }
        for item in questions
    ]
    await insert_rows("planned_questions", question_rows)
    await persist_interview_plan(org_id=run.org_id, candidate_id=candidate_id, plan_id=plan_id, run_id=run.id)
    return {
        "ok": True,
        "interview_designer": {
            "plan_id": plan_id,
            "count": len(question_rows),
            "warnings": designed.warnings,
        },
    }
