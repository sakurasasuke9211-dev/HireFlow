from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json
from hireflow_domain.enums import EvidenceDimension, MatchStatus

PROMPT_VERSION = "interview_designer.v1"
DIMENSIONS = [item.value for item in EvidenceDimension]

SYSTEM = """You are HireFlow's Interview Designer. Write a candidate-specific interview plan for a recruiter to use outside HireFlow.

Rules:
- Write questions for EVERY gap provided. Do not skip a requirement_id.
- One primary question per gap, plus 3-5 planned follow-ups the recruiter can ask live.
- Every question MUST use the given requirement_id. Do not invent requirements.
- Questions must be specific to THIS candidate's resume (roles, projects, missing evidence). Two candidates on the same JD must get different questions.
- MISSING gaps: fair open probe. Ask what they have actually built. Not a gotcha. Never "Do you know X?"
- UNCLEAR or PARTIALLY_MATCHED: ask for artifacts of work, complexity, ownership, and outcome.
- planned_followups are extra questions, not restatements of the primary.
- evidence_target: subset of named, applied, complexity, professional, ownership, outcome that would upgrade the status.
- Do not include claim IDs, UUIDs, or database identifiers in prompts.
- Do not write a hiring decision. HireFlow does not conduct the interview.
"""


class PlannedQuestionItem(BaseModel):
    requirement_id: str
    prompt: str
    planned_followups: list[str] = Field(default_factory=list)
    evidence_target: list[str] = Field(default_factory=list)


class InterviewDesignerOutput(BaseModel):
    agent: str = "interview_designer"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    questions: list[PlannedQuestionItem] = Field(default_factory=list)


def _coerce_targets(raw: list[str], *, status: MatchStatus, flags: dict | None) -> list[str]:
    allowed = {item.value for item in EvidenceDimension}
    targets = [item for item in raw if item in allowed]
    if targets:
        return targets
    flags = flags or {}
    missing = [name for name in DIMENSIONS if not int(flags.get(name) or 0)]
    if status == MatchStatus.MISSING:
        return ["named", "applied", "professional"]
    if status == MatchStatus.UNCLEAR:
        return ["applied", "complexity", "ownership", "outcome"]
    return missing or ["complexity", "ownership", "outcome"]


def default_followups(label: str, status: MatchStatus, themes: list[str]) -> list[str]:
    questions = [
        f"What system used {label}, and what was the production impact?",
        f"What part of the {label} work did you personally own?",
        f"What was the hardest part of the {label} work, and how did you handle it?",
        f"What changed because of your {label} contribution? How did you measure it?",
        f"Who else was involved in the {label} work, and what was yours versus the team’s?",
    ]
    if status != MatchStatus.MISSING:
        questions.insert(
            0,
            f"Walk me through an artifact of the {label} work — a doc, ticket, design, or demo.",
        )
    extras = []
    for theme in themes:
        text = str(theme).strip()
        if not text:
            continue
        extras.append(f"Probe {label} on {text}: what did you personally do, and what was the result?")
    merged: list[str] = []
    for item in extras + questions:
        if item not in merged:
            merged.append(item)
    return merged[:6]


def default_plan(gaps: list[dict], *, profile: dict | None = None) -> InterviewDesignerOutput:
    role = None
    if profile:
        roles = profile.get("roles") or []
        role = roles[0] if roles else profile.get("summary")
        if isinstance(role, str):
            role = role.strip()[:80] or None
        else:
            role = None
    ranked = sorted(
        gaps,
        key=lambda item: (
            {"blocker": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("severity")), 9),
            int(item.get("sort_order") or 0),
        ),
    )
    questions: list[PlannedQuestionItem] = []
    for item in ranked:
        status = MatchStatus(item.get("status") or MatchStatus.UNCLEAR.value)
        label = str(item.get("label") or "this requirement")
        quote = (item.get("quote") or "").strip() or None
        if quote and len(quote) > 140:
            quote = quote[:137] + "…"
        questions.append(
            PlannedQuestionItem(
                requirement_id=str(item["requirement_id"]),
                prompt=default_prompt(label=label, status=status, role=role, quote=quote),
                planned_followups=default_followups(label, status, list(item.get("themes") or [])),
                evidence_target=_coerce_targets([], status=status, flags=item.get("dimension_flags")),
            )
        )
    warnings = []
    if not questions:
        warnings.append("No gaps to probe; interview plan has no questions.")
    return InterviewDesignerOutput(questions=questions, warnings=warnings)


def default_prompt(*, label: str, status: MatchStatus, role: str | None, quote: str | None) -> str:
    in_role = f" In your {role} work," if role else ""
    if status == MatchStatus.MISSING:
        return (
            f"Walk me through a time you used {label} on a real system.{in_role} "
            "What did you build, and what was yours to own?"
        )
    if status == MatchStatus.UNCLEAR:
        hint = f" The resume only hints at this (“{quote}”)." if quote else ""
        return (
            f"{label} is listed without showing the work.{hint}{in_role} "
            "What artifact did you produce, and what was hard about it?"
        )
    hint = f" You appear to have used {label} (“{quote}”)." if quote else f" You appear to have used {label}."
    return (
        f"{hint}{in_role} What was the hardest part you personally owned, "
        "and what measurable outcome did it produce?"
    )


async def design_interview_plan(
    *,
    gaps: list[dict],
    profile: dict | None,
    config: LLMConfig,
) -> InterviewDesignerOutput:
    fallback = default_plan(gaps, profile=profile)
    if not gaps:
        return fallback
    try:
        generated = await complete_json(
            config,
            system=SYSTEM,
            user=(
                "Write interview questions for EVERY gap. Use only these requirement_ids.\n\n"
                f"Profile:\n{profile or {}}\n\nGaps:\n{gaps}"
            ),
            schema=InterviewDesignerOutput,
            agent="interview_designer",
        )
    except LLMError:
        return fallback
    by_req = {item["requirement_id"]: item for item in gaps}
    questions: list[PlannedQuestionItem] = []
    seen: set[str] = set()
    for item in generated.questions:
        gap = by_req.get(item.requirement_id)
        if gap is None or item.requirement_id in seen:
            continue
        seen.add(item.requirement_id)
        status = MatchStatus(gap.get("status") or MatchStatus.UNCLEAR.value)
        label = str(gap.get("label") or "this requirement")
        prompt = (item.prompt or "").strip() or default_prompt(
            label=label,
            status=status,
            role=None,
            quote=gap.get("quote"),
        )
        followups = [line.strip() for line in item.planned_followups if str(line).strip()]
        defaults = default_followups(label, status, list(gap.get("themes") or []))
        for extra in defaults:
            if extra not in followups:
                followups.append(extra)
        questions.append(
            PlannedQuestionItem(
                requirement_id=item.requirement_id,
                prompt=prompt,
                planned_followups=followups[:6],
                evidence_target=_coerce_targets(
                    item.evidence_target,
                    status=status,
                    flags=gap.get("dimension_flags"),
                ),
            )
        )
    for item in fallback.questions:
        if item.requirement_id not in seen:
            questions.append(item)
    if not questions:
        return fallback
    generated.questions = questions
    return generated
