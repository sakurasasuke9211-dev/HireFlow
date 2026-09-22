from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid

from hireflow_agents.gap_analyst import default_goal, default_severity, default_themes
from hireflow_agents.graphs.screening import run_gaps, run_match
from hireflow_agents.llm import LLMError
from hireflow_agents.matcher import candidate_years, coerce_flags, resolve_requirement_status
from hireflow_api.db import delete_rows, fetch_in, fetch_many, fetch_one, insert_row, insert_rows, update_rows
from hireflow_api.llm import agent_llm_config
from hireflow_api.models import AgentTrace, Candidate, Claim, PipelineRun, Profile, Requirement, utcnow
from hireflow_api.services import scrub_internal_ids
from hireflow_domain.enums import MatchStatus, RequirementPriority
from hireflow_domain.schemas import DimensionFlags

logger = logging.getLogger(__name__)


async def match_candidate_job(candidate_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    if run_row is None:
        logger.error("match job missing run %s", run_id)
        return
    run = PipelineRun.model_validate(run_row)
    await update_rows("pipeline_runs", {"status": "running", "started_at": utcnow()}, id=run.id)

    started = time.perf_counter()
    input_payload = {"candidate_id": candidate_id}
    output_payload: dict = {}
    error = None
    status = "succeeded"
    try:
        output_payload = await _run_match(run, candidate_id)
    except LLMError as exc:
        logger.warning("matcher LLM failed; falling back to rules-only match: %s", exc)
        try:
            output_payload = await _run_rules_match(run, candidate_id)
            status = "succeeded"
            error = None
        except Exception as fallback_exc:
            logger.exception("rules-only match failed")
            status = "failed"
            error = str(fallback_exc)
            output_payload = {"ok": False, "error": str(fallback_exc)}
    except Exception as exc:
        logger.exception("match failed")
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}

    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    for agent, prompt_version in (("matcher", "matcher.v5"), ("gap_analyst", "gap_analyst.v1")):
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
            from hireflow_api.services import start_plan_unless_active

            await start_plan_unless_active(org_id=run.org_id, candidate_id=candidate_id)
        except Exception:
            logger.exception("could not enqueue interview plan")

async def _persist_matches(
    *,
    run: PipelineRun,
    candidate: Candidate,
    requirements: list[Requirement],
    profile: dict | None,
    claim_dicts: list[dict],
    claim_ids: set[str],
    by_req: dict,
) -> dict:
    resolved_experience_years = candidate_years(profile, claim_dicts)

    existing_matches = await fetch_many("match_results", candidate_id=candidate.id)
    existing_ids = [row["id"] for row in existing_matches]
    preserved: dict[str, dict] = {}
    if existing_ids:
        existing_gaps = await fetch_in("gaps", "match_result_id", existing_ids)
        match_by_id = {row["id"]: row for row in existing_matches}
        for gap in existing_gaps:
            parent = match_by_id.get(gap["match_result_id"])
            if parent:
                preserved[parent["requirement_id"]] = {
                    "deal_breaker": bool(gap.get("deal_breaker")),
                    "skip_probe": bool(gap.get("skip_probe")),
                }

    match_rows: list[dict] = []
    computed: list[dict] = []
    for requirement in requirements:
        item = by_req.get(requirement.id)
        supporting = [cid for cid in (item.supporting_claim_ids if item else []) if cid in claim_ids]
        flags = coerce_flags(
            item.dimension_flags if item else DimensionFlags(),
            claims=claim_dicts,
            supporting_ids=supporting,
            conflicting=bool(item.conflicting) if item else False,
            category=requirement.category,
        )
        status = resolve_requirement_status(
            requirement_text=requirement.text,
            normalized_label=requirement.normalized_label or "",
            category=requirement.category,
            profile=profile,
            claims=claim_dicts,
            flags=flags,
            conflicting=bool(item.conflicting) if item else False,
            experience_years=resolved_experience_years,
        )
        rationale = scrub_internal_ids((item.rationale if item else "").strip()) if item else ""
        if not rationale:
            rationale = "No evidence found." if status == MatchStatus.MISSING else "Evidence found in profile or claims."
        match_id = str(uuid.uuid4())
        match_rows.append(
            {
                "id": match_id,
                "org_id": candidate.org_id,
                "job_id": candidate.job_id,
                "candidate_id": candidate.id,
                "requirement_id": requirement.id,
                "status": status.value,
                "confidence": item.confidence if item else 0,
                "rationale": rationale,
                "dimension_flags": flags.model_dump(),
                "supporting_claim_ids": supporting,
                "run_id": run.id,
                "created_at": utcnow(),
            }
        )
        computed.append(
            {
                "requirement_id": requirement.id,
                "match_id": match_id,
                "label": requirement.normalized_label,
                "priority": requirement.priority,
                "status": status.value,
                "dimension_flags": flags.model_dump(),
                "rationale": rationale,
            }
        )

    old_matches = await fetch_many("match_results", candidate_id=candidate.id)
    for row in old_matches:
        await delete_rows("gaps", match_result_id=row["id"])
    await delete_rows("match_results", candidate_id=candidate.id)
    await insert_rows("match_results", match_rows)

    gap_input = [
        {
            "requirement_id": row["requirement_id"],
            "label": row["label"],
            "priority": row["priority"],
            "status": row["status"],
            "rationale": row["rationale"],
            "dimension_flags": row["dimension_flags"],
        }
        for row in computed
        if row["status"] != MatchStatus.MATCHED.value
    ]
    gap_out = None
    if gap_input:
        try:
            gap_out = await run_gaps(matches=gap_input, config=agent_llm_config("gap_analyst"))
        except LLMError:
            logger.warning("gap analyst unavailable; using default gap text")

    proposed = {item.requirement_id: item for item in (gap_out.gaps if gap_out else [])}

    gap_rows: list[dict] = []
    for row in computed:
        status = MatchStatus(row["status"])
        if status == MatchStatus.MATCHED:
            continue
        priority = row["priority"]
        required = priority == RequirementPriority.must_have.value
        item = proposed.get(row["requirement_id"])
        if item is None and not required:
            continue
        flags_prev = preserved.get(row["requirement_id"], {})
        gap_rows.append(
            {
                "id": str(uuid.uuid4()),
                "org_id": candidate.org_id,
                "match_result_id": row["match_id"],
                "severity": item.severity.value if item else default_severity(status, priority).value,
                "investigation_goal": (item.investigation_goal.strip() if item else "")
                or default_goal(row["label"], status),
                "suggested_probe_themes": (item.suggested_probe_themes if item else None) or default_themes(status),
                "deal_breaker": bool(flags_prev.get("deal_breaker")),
                "skip_probe": bool(flags_prev.get("skip_probe")),
            }
        )

    if gap_rows:
        try:
            await insert_rows("gaps", gap_rows)
        except Exception:
            logger.exception("gap insert failed; match results kept")
    return {
        "ok": True,
        "matcher": {"count": len(match_rows), "warnings": []},
        "gap_analyst": {"count": len(gap_rows), "warnings": gap_out.warnings if gap_out else []},
    }


async def _load_match_inputs(candidate_id: str, run: PipelineRun) -> tuple[Candidate, list[Requirement], list[Claim], dict | None, list[dict]]:
    candidate_row = await fetch_one("candidates", id=candidate_id)
    if candidate_row is None:
        raise ValueError("Candidate not found")
    candidate = Candidate.model_validate(candidate_row)
    if candidate.org_id != run.org_id:
        raise ValueError("Candidate not found")

    requirements = [
        Requirement.model_validate(row)
        for row in await fetch_many("requirements", job_id=candidate.job_id, order="sort_order")
    ]
    if not requirements:
        raise ValueError("Parse and confirm JD requirements before matching")
    claims = [Claim.model_validate(row) for row in await fetch_many("claims", candidate_id=candidate.id)]
    profile_row = await fetch_one("profiles", candidate_id=candidate.id)
    if profile_row is None and not claims:
        raise ValueError("Parse the resume before matching")

    claim_payload = [
        {
            "id": item.id,
            "kind": item.kind,
            "text": item.text,
            "skill_label": item.skill_label,
            "years": item.years,
            "quote": item.quote,
        }
        for item in claims
    ]
    profile = None
    if profile_row:
        profile_model = Profile.model_validate(profile_row)
        profile = {
            "full_name": profile_model.full_name,
            "summary": profile_model.summary,
            "years_experience": profile_model.years_experience,
            "education": list(profile_model.education or []),
            "skills_listed": profile_model.skills_listed,
            "roles": profile_model.roles,
        }
    return candidate, requirements, claims, profile, claim_payload


async def _run_rules_match(run: PipelineRun, candidate_id: str) -> dict:
    candidate, requirements, claims, profile, claim_payload = await _load_match_inputs(candidate_id, run)
    by_req = {requirement.id: None for requirement in requirements}
    return await _persist_matches(
        run=run,
        candidate=candidate,
        requirements=requirements,
        profile=profile,
        claim_dicts=claim_payload,
        claim_ids={item.id for item in claims},
        by_req=by_req,
    )


async def _run_match(run: PipelineRun, candidate_id: str) -> dict:
    candidate, requirements, claims, profile, claim_payload = await _load_match_inputs(candidate_id, run)
    req_payload = [
        {
            "id": item.id,
            "text": item.text,
            "normalized_label": item.normalized_label,
            "category": item.category,
            "priority": item.priority,
        }
        for item in requirements
    ]

    matcher_out = await run_match(
        requirements=req_payload,
        claims=claim_payload,
        profile=profile,
        config=agent_llm_config("matcher"),
    )
    if len(matcher_out.results) != len(requirements):
        raise ValueError("Matcher returned a partial requirement set")
    by_req = {item.requirement_id: item for item in matcher_out.results}
    result = await _persist_matches(
        run=run,
        candidate=candidate,
        requirements=requirements,
        profile=profile,
        claim_dicts=claim_payload,
        claim_ids={item.id for item in claims},
        by_req=by_req,
    )
    result["matcher"]["warnings"] = matcher_out.warnings
    return result
