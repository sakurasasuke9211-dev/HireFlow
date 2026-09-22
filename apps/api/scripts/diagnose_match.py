"""Diagnose match status resolution for a candidate."""
from __future__ import annotations

import asyncio
import json
import sys

from hireflow_agents.matcher import candidate_years, resolve_requirement_status
from hireflow_api.db import fetch_many, fetch_one
from hireflow_api.models import Claim, MatchResult, Profile, Requirement
from hireflow_api.services import _claim_dicts, _profile_dict, _resolved_match_row
from hireflow_domain.schemas import DimensionFlags


async def diagnose(candidate_id: str) -> None:
    profile_row = await fetch_one("profiles", candidate_id=candidate_id)
    profile = _profile_dict(Profile.model_validate(profile_row) if profile_row else None)
    claims = [Claim.model_validate(row) for row in await fetch_many("claims", candidate_id=candidate_id)]
    claim_dicts = _claim_dicts(claims)
    years = candidate_years(profile, claim_dicts)

    candidate = await fetch_one("candidates", id=candidate_id)
    if not candidate:
        print(f"Candidate {candidate_id} not found")
        return

    requirements = [
        Requirement.model_validate(row)
        for row in await fetch_many("requirements", job_id=candidate["job_id"])
    ]
    matches = await fetch_many("match_results", candidate_id=candidate_id)

    print(f"Candidate: {candidate.get('full_name')}")
    print(f"years_experience profile field: {(profile or {}).get('years_experience')}")
    print(f"resolved years: {years}")
    print(f"summary snippet: {str((profile or {}).get('summary') or '')[:120]}")
    print(f"education: {(profile or {}).get('education')}")
    print("---")

    req_map = {r.id: r for r in requirements}
    for row in matches:
        req = req_map.get(row["requirement_id"])
        if req is None:
            continue
        label = req.normalized_label or req.text
        if label not in {
            "Experience 2-3 years",
            "MBA or Bachelor's in Business/Engineering",
            "SQL",
            "Communication and interpersonal",
        } and "experience" not in label.lower() and "mba" not in label.lower():
            continue

        match = MatchResult.model_validate(row)
        flags = DimensionFlags.model_validate(row.get("dimension_flags") or {})
        resolved = resolve_requirement_status(
            requirement_text=req.text,
            normalized_label=req.normalized_label or "",
            category=req.category,
            profile=profile,
            claims=claim_dicts,
            flags=flags,
            experience_years=years,
        )
        fixed = _resolved_match_row(
            match,
            req,
            profile=profile,
            claim_dicts=claim_dicts,
            experience_years=years,
        )
        print(
            json.dumps(
                {
                    "label": label,
                    "category": req.category,
                    "db_status": row["status"],
                    "resolved": resolved.value,
                    "fixed_row": fixed.status,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else "fa6abd37-eb9d-4fbb-80c2-191e89519453"
    asyncio.run(diagnose(cid))
