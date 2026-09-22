from __future__ import annotations

import re

from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json
from hireflow_domain.enums import EvidenceDimension, ProbeVerdict

PROMPT_VERSION = "prober.v1"
MAX_FOLLOWUPS = 2
DIMENSIONS = [item.value for item in EvidenceDimension]
_YEARS = re.compile(
    r"\b(?:\d+\+?\s*(?:years?|yrs?)|(?:for|over|about)\s+\d+\s*(?:years?|yrs?)|years?\s+of\s+experience)\b",
    re.IGNORECASE,
)
_ARTIFACT = re.compile(
    r"\b(built|build|designed|shipped|deployed|owned|implemented|architect|architecture|system|project|service|production|scaled|migrat|launched|ticket|dashboard|pipeline|api)\b",
    re.IGNORECASE,
)
_CONFIRMED_MISSING = re.compile(
    r"\b(never used|don't have|do not have|haven't used|have not used|no experience|not used|didn't use|did not use)\b",
    re.IGNORECASE,
)
_CONTRADICTION = re.compile(
    r"\b(resume is wrong|that was a mistake|actually never|didn't do that|did not do that|that isn't true|that is not true)\b",
    re.IGNORECASE,
)

SYSTEM = """You are HireFlow's Prober. Score a provided interview transcript against JD requirements.

Rules:
- You read the record. You do not interview the candidate.
- verdict is sufficient | shallow | not_discussed | confirmed_missing | contradiction.
- "I have used X for N years" is ALWAYS shallow unless the transcript also describes a system, complexity, ownership, or outcome.
- Years are not proof.
- If a requirement was not discussed, verdict is not_discussed.
- If the candidate says they have not used it, verdict is confirmed_missing.
- If the transcript contradicts the resume claim, verdict is contradiction.
- remaining_followups: at most 2 questions targeting the highest missing evidence dimensions. Empty when sufficient, confirmed_missing, or contradiction.
- missing_dimensions: named, applied, complexity, professional, ownership, outcome.
- supporting_turn_ids must be IDs from the provided turns.
- Do not write a hiring decision. Do not include UUIDs in rationale or questions.
"""


class ProbeItem(BaseModel):
    requirement_id: str
    verdict: str
    missing_dimensions: list[str] = Field(default_factory=list)
    supporting_turn_ids: list[str] = Field(default_factory=list)
    remaining_followups: list[str] = Field(default_factory=list)
    rationale: str


class ProberOutput(BaseModel):
    agent: str = "prober"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    results: list[ProbeItem] = Field(default_factory=list)


def is_years_only(text: str) -> bool:
    blob = text or ""
    return bool(_YEARS.search(blob)) and not bool(_ARTIFACT.search(blob))


def remaining_followups_for(label: str, missing: list[str]) -> list[str]:
    name = label.strip() or "this requirement"
    by_dim = {
        "named": f"Have you used {name} in a real system? If yes, which one?",
        "applied": f"Walk me through a specific system you built with {name}. What did you build?",
        "complexity": f"What was the hardest part of the {name} work, and how did you handle it?",
        "professional": f"Was the {name} work professional, academic, or a side project?",
        "ownership": f"What part of the {name} work did you personally own versus the team?",
        "outcome": f"What changed because of your {name} contribution, and how did you measure it?",
    }
    ordered = [item for item in missing if item in by_dim] or ["applied", "ownership"]
    questions: list[str] = []
    for dim in ordered:
        question = by_dim.get(dim)
        if question and question not in questions:
            questions.append(question)
        if len(questions) >= MAX_FOLLOWUPS:
            break
    return questions[:MAX_FOLLOWUPS]


def related_turns(requirement: dict, turns: list[dict]) -> list[dict]:
    req_id = str(requirement.get("id") or "")
    label = str(requirement.get("label") or "").strip().lower()
    tokens = {item for item in re.findall(r"[a-z0-9+#.]+", label) if len(item) > 1}
    related: list[dict] = []
    for turn in turns:
        if str(turn.get("requirement_id") or "") == req_id:
            related.append(turn)
            continue
        text = str(turn.get("text") or "").lower()
        if label and label in text:
            related.append(turn)
            continue
        turn_tokens = {item for item in re.findall(r"[a-z0-9+#.]+", text) if len(item) > 1}
        if tokens and len(tokens & turn_tokens) / max(len(tokens), 1) >= 0.5:
            related.append(turn)
    return related


def heuristic_probe(requirement: dict, turns: list[dict]) -> ProbeItem:
    related = related_turns(requirement, turns)
    blob = " ".join(str(item.get("text") or "") for item in related)
    ids = [str(item.get("id")) for item in related if item.get("id")]
    label = str(requirement.get("label") or "this requirement")
    target = [item for item in (requirement.get("evidence_target") or DIMENSIONS) if item in DIMENSIONS]
    missing = [item for item in (target or DIMENSIONS) if item != "named"]
    if not blob.strip():
        return ProbeItem(
            requirement_id=str(requirement["id"]),
            verdict=ProbeVerdict.not_discussed.value,
            missing_dimensions=target or DIMENSIONS[:],
            supporting_turn_ids=[],
            remaining_followups=remaining_followups_for(label, target or ["applied", "ownership"]),
            rationale=f"{label} was not discussed in this transcript.",
        )
    if _CONTRADICTION.search(blob):
        return ProbeItem(
            requirement_id=str(requirement["id"]),
            verdict=ProbeVerdict.contradiction.value,
            missing_dimensions=[],
            supporting_turn_ids=ids,
            remaining_followups=[],
            rationale=f"The transcript contradicts the resume claim on {label}.",
        )
    if _CONFIRMED_MISSING.search(blob):
        return ProbeItem(
            requirement_id=str(requirement["id"]),
            verdict=ProbeVerdict.confirmed_missing.value,
            missing_dimensions=target or DIMENSIONS[:],
            supporting_turn_ids=ids,
            remaining_followups=[],
            rationale=f"The candidate said they have not used {label}.",
        )
    if is_years_only(blob):
        return ProbeItem(
            requirement_id=str(requirement["id"]),
            verdict=ProbeVerdict.shallow.value,
            missing_dimensions=missing or ["applied", "complexity", "ownership", "outcome"],
            supporting_turn_ids=ids,
            remaining_followups=remaining_followups_for(label, missing or ["applied", "ownership"]),
            rationale=f"The transcript only restates years of {label}. Years are not proof of applied work.",
        )
    if _ARTIFACT.search(blob):
        return ProbeItem(
            requirement_id=str(requirement["id"]),
            verdict=ProbeVerdict.sufficient.value,
            missing_dimensions=[],
            supporting_turn_ids=ids,
            remaining_followups=[],
            rationale=f"The transcript describes applied {label} work, not only years.",
        )
    return ProbeItem(
        requirement_id=str(requirement["id"]),
        verdict=ProbeVerdict.shallow.value,
        missing_dimensions=missing or ["applied", "complexity", "ownership"],
        supporting_turn_ids=ids,
        remaining_followups=remaining_followups_for(label, missing or ["applied", "ownership"]),
        rationale=f"{label} was mentioned without enough depth on what was built, owned, or shipped.",
    )


def coerce_probe(item: ProbeItem, requirement: dict, turns: list[dict]) -> ProbeItem:
    related = related_turns(requirement, turns)
    blob = " ".join(str(turn.get("text") or "") for turn in related)
    allowed_ids = {str(turn.get("id")) for turn in related if turn.get("id")}
    label = str(requirement.get("label") or "this requirement")
    try:
        verdict = ProbeVerdict(item.verdict)
    except ValueError:
        verdict = ProbeVerdict.not_discussed
    if not blob.strip() and verdict not in {ProbeVerdict.confirmed_missing, ProbeVerdict.contradiction}:
        verdict = ProbeVerdict.not_discussed
    if blob.strip() and is_years_only(blob) and verdict == ProbeVerdict.sufficient:
        verdict = ProbeVerdict.shallow
    if blob.strip() and _CONFIRMED_MISSING.search(blob):
        verdict = ProbeVerdict.confirmed_missing
    if blob.strip() and _CONTRADICTION.search(blob):
        verdict = ProbeVerdict.contradiction
    allowed_dims = {item.value for item in EvidenceDimension}
    missing = [dim for dim in item.missing_dimensions if dim in allowed_dims]
    target = [dim for dim in (requirement.get("evidence_target") or []) if dim in allowed_dims]
    if verdict == ProbeVerdict.sufficient:
        missing = []
    elif not missing:
        missing = [dim for dim in (target or DIMENSIONS) if dim not in {"named"}] or ["applied", "ownership"]
    support = [turn_id for turn_id in item.supporting_turn_ids if turn_id in allowed_ids] or [
        str(turn.get("id")) for turn in related if turn.get("id")
    ]
    followups: list[str] = []
    if verdict in {ProbeVerdict.shallow, ProbeVerdict.not_discussed}:
        followups = [line.strip() for line in item.remaining_followups if line.strip()][:MAX_FOLLOWUPS]
        if not followups:
            followups = remaining_followups_for(label, missing)
        followups = followups[:MAX_FOLLOWUPS]
    rationale = (item.rationale or "").strip() or heuristic_probe(requirement, turns).rationale
    if verdict == ProbeVerdict.shallow and is_years_only(blob):
        rationale = f"The transcript only restates years of {label}. Years are not proof of applied work."
    return ProbeItem(
        requirement_id=str(requirement["id"]),
        verdict=verdict.value,
        missing_dimensions=missing,
        supporting_turn_ids=support,
        remaining_followups=followups,
        rationale=rationale,
    )


def fallback_probe(*, requirements: list[dict], turns: list[dict]) -> ProberOutput:
    results = [heuristic_probe(requirement, turns) for requirement in requirements]
    warnings = []
    if any(item.verdict == ProbeVerdict.shallow.value and is_years_only(
        " ".join(str(turn.get("text") or "") for turn in related_turns(requirement, turns))
    ) for requirement, item in zip(requirements, results, strict=False)):
        warnings.append("Years-only answers were scored shallow.")
    return ProberOutput(warnings=warnings, results=results)


async def probe_transcript(
    *,
    requirements: list[dict],
    turns: list[dict],
    config: LLMConfig,
) -> ProberOutput:
    fallback = fallback_probe(requirements=requirements, turns=turns)
    if not requirements:
        return ProberOutput(warnings=["No requirements to probe."], results=[])
    try:
        parsed = await complete_json(
            config,
            system=SYSTEM,
            user=(
                "Score transcript coverage for each requirement. Years-only is shallow.\n\n"
                f"Requirements:\n{requirements}\n\n"
                f"Turns:\n{turns}"
            ),
            schema=ProberOutput,
            agent="prober",
        )
    except LLMError:
        return fallback
    by_id = {item.requirement_id: item for item in parsed.results}
    results = []
    for requirement in requirements:
        item = by_id.get(str(requirement["id"])) or heuristic_probe(requirement, turns)
        results.append(coerce_probe(item, requirement, turns))
    warnings = list(parsed.warnings)
    if any(item.verdict == ProbeVerdict.shallow.value for item in results):
        if "Shallow coverage still needs a follow-up interview." not in warnings:
            warnings.append("Shallow coverage still needs a follow-up interview.")
    return ProberOutput(warnings=warnings, results=results)
