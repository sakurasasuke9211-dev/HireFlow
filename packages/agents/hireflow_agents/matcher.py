import re

from pydantic import BaseModel, Field

from hireflow_agents.experience import classify_experience_years, resolve_years_experience
from hireflow_agents.llm import LLMConfig, complete_json
from hireflow_domain.enums import ClaimKind, MatchStatus, RequirementCategory
from hireflow_domain.schemas import DimensionFlags

PROMPT_VERSION = "matcher.v5"
EVIDENCE_KINDS = {ClaimKind.project, ClaimKind.implied_skill, ClaimKind.education, ClaimKind.other}

SYSTEM = """You are HireFlow's Matcher. Score resume evidence against each JD requirement.

You do NOT assign MATCHED / PARTIALLY_MATCHED / MISSING / UNCLEAR. You only score 0/1 dimension flags and pick supporting claim IDs.

Dimensions (0 or 1 only):
- named: requirement is named or clearly aliased in the resume
- applied: used in a project or job bullet, not only a skills list or years line
- complexity: scale, architecture, or difficulty is described
- professional: used in employment, not only coursework
- ownership: individual contribution is described (not only team "we")
- outcome: a measurable result is described

Category-specific scoring (use requirement.category):
- education: set named=1 when an explicit degree or program satisfies the requirement (MBA, B.Tech, Bachelor's, etc.). Set applied=1 for kind=education claims listing the degree. Do NOT require project usage for education.
- experience: set named=1 when total years are evidenced. JD bands like "2-3 years" mean MATCHED inside the band and PARTIALLY_MATCHED when above the upper bound (e.g. 4 years for 2-3). Use profile.years_experience, years_claim, intro/summary, and employment date ranges. Set professional=1 when derived from employment (not coursework).
- soft_skill: treat related resume language as named aliases — e.g. stakeholder management / cross-functional collaboration → communication & interpersonal; presenting / client-facing → communication; sales funnel / lead generation / CRM pipeline → presales familiarity. Set applied=1 when the skill appears in a work or internship bullet (kind=project or implied_skill), not only a skills list.
- skill / domain / tooling: standard rules below.

Semantic aliases (named=1 when resume uses equivalent language):
- communication, interpersonal → stakeholder management, client engagement, cross-functional, liaison, presenting, collaboration
- analytical, problem solving → data analysis, root cause, insights, metrics, dashboards, optimization, modeling, requirements analysis
- presales, pre-sales → sales funnel, pipeline, lead qualification, CRM, prospecting, RFP support
- manufacturing (domain) → production, plant, shop floor, industrial, supply chain in manufacturing context

Hard rules:
- A years_claim such as "Python — 4 years" is named at most for skill requirements. For experience-category requirements about total/professional tenure, a years_claim for total experience OR profile.years_experience counts as named=1 and professional=1.
- A skills-list-only mention is named at most, never applied (except education category).
- Do not invent claims. supporting_claim_ids must be IDs from the provided claims.
- If nothing relevant exists, all flags are 0 and supporting_claim_ids is empty.
- If quotes conflict, set conflicting=true.
- Rationale must describe the evidence in plain language. Never include claim IDs, UUIDs, or the word "id" with a database identifier.
- Return one result per requirement_id. Do not drop a requirement.
"""


class MatcherItem(BaseModel):
    requirement_id: str
    confidence: float = 0.0
    rationale: str
    dimension_flags: DimensionFlags = Field(default_factory=DimensionFlags)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    conflicting: bool = False


class MatcherOutput(BaseModel):
    agent: str = "matcher"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    results: list[MatcherItem] = Field(default_factory=list)


def _flag(value: int | bool) -> int:
    return 1 if int(value) else 0


def coerce_flags(
    flags: DimensionFlags,
    *,
    claims: list[dict],
    supporting_ids: list[str],
    conflicting: bool,
    category: RequirementCategory | str | None = None,
) -> DimensionFlags:
    by_id = {str(claim["id"]): claim for claim in claims}
    supporting = [by_id[cid] for cid in supporting_ids if cid in by_id]
    named = _flag(flags.named)
    applied = _flag(flags.applied)
    complexity = _flag(flags.complexity)
    professional = _flag(flags.professional)
    ownership = _flag(flags.ownership)
    outcome = _flag(flags.outcome)

    if not supporting:
        return DimensionFlags()

    try:
        cat = RequirementCategory(category) if category else None
    except ValueError:
        cat = None

    kinds = {str(claim.get("kind")) for claim in supporting}
    evidence = False
    for kind in kinds:
        try:
            evidence = evidence or ClaimKind(kind) in EVIDENCE_KINDS
        except ValueError:
            continue

    only_shallow = kinds <= {ClaimKind.years_claim.value, ClaimKind.skill.value} and not evidence
    if only_shallow and cat != RequirementCategory.experience:
        applied = 0
        complexity = 0
        ownership = 0
        outcome = 0
        professional = 0

    if cat == RequirementCategory.education and ClaimKind.education.value in kinds:
        named = max(named, 1)
        applied = max(applied, 1)

    if cat == RequirementCategory.experience and ClaimKind.years_claim.value in kinds:
        named = max(named, 1)
        professional = max(professional, 1)

    if conflicting:
        applied = min(applied, 1)

    return DimensionFlags(
        named=named,
        applied=applied,
        complexity=complexity,
        professional=professional,
        ownership=ownership,
        outcome=outcome,
    )


def _candidate_years(profile: dict | None, claims: list[dict]) -> float | None:
    claim_texts = [
        f"{claim.get('text') or ''} {claim.get('quote') or ''}" for claim in claims
    ]
    years_claim_values: list[float] = []
    for claim in claims:
        if claim.get("kind") != ClaimKind.years_claim.value:
            continue
        years = claim.get("years")
        if years is None:
            continue
        try:
            years_claim_values.append(float(years))
        except (TypeError, ValueError):
            continue
    resolved = resolve_years_experience(
        summary=str((profile or {}).get("summary") or ""),
        claim_texts=claim_texts,
        current=(profile or {}).get("years_experience"),
    )
    if resolved is not None:
        return resolved
    return max(years_claim_values) if years_claim_values else None


_EDU_ALIASES: dict[str, tuple[str, ...]] = {
    "mba": ("mba", "master of business", "pgdm", "iim"),
    "bachelor": ("bachelor", "b.tech", "btech", "b.e.", "be ", "b.e ", "bs ", "b.s.", "undergraduate"),
    "business": ("business", "management", "commerce", "mba"),
    "engineering": ("engineering", "b.tech", "btech", "b.e.", "technology", "technical"),
}


def _education_sources(profile: dict | None, claims: list[dict] | None) -> list[str]:
    sources = list((profile or {}).get("education") or [])
    for claim in claims or []:
        if claim.get("kind") == ClaimKind.education.value:
            sources.append(str(claim.get("text") or claim.get("quote") or ""))
    if profile and profile.get("summary"):
        sources.append(str(profile["summary"]))
    return sources


def _education_satisfies(requirement_text: str, sources: list[str]) -> bool:
    blob = " ".join(sources).lower()
    if not blob.strip():
        return False
    req = requirement_text.lower()
    needs_mba = "mba" in req
    needs_bachelor = "bachelor" in req or "b.tech" in req or "btech" in req
    needs_business = "business" in req
    needs_engineering = "engineering" in req

    has_mba = any(alias in blob for alias in _EDU_ALIASES["mba"])
    has_bachelor = any(alias in blob for alias in _EDU_ALIASES["bachelor"])
    has_business = any(alias in blob for alias in _EDU_ALIASES["business"])
    has_engineering = any(alias in blob for alias in _EDU_ALIASES["engineering"])

    if " or " in req:
        options: list[bool] = []
        if needs_mba:
            options.append(has_mba)
        if needs_bachelor:
            options.append(has_bachelor)
        if needs_business and not needs_mba:
            options.append(has_business or has_mba)
        if needs_engineering and not needs_bachelor:
            options.append(has_engineering or has_bachelor)
        if options:
            return any(options)
    if needs_mba and has_mba:
        return True
    if needs_bachelor and has_bachelor:
        return True
    if needs_business and has_business:
        return True
    if needs_engineering and has_engineering:
        return True
    return any(token in blob for token in re.findall(r"[a-z][a-z.]+", req) if len(token) > 3)


def _education_match_status(requirement_text: str, sources: list[str]) -> MatchStatus:
    if not _education_satisfies(requirement_text, sources):
        return MatchStatus.MISSING
    blob = " ".join(sources).lower()
    has_mba = any(alias in blob for alias in _EDU_ALIASES["mba"])
    has_bachelor = any(alias in blob for alias in _EDU_ALIASES["bachelor"])
    has_engineering = any(alias in blob for alias in _EDU_ALIASES["engineering"])
    req = requirement_text.lower()
    if has_mba and (has_engineering or has_bachelor):
        return MatchStatus.MATCHED
    if " or " in req and (has_mba or has_bachelor or has_engineering):
        return MatchStatus.MATCHED
    return MatchStatus.MATCHED


_SOFT_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "communication": (
        "communication",
        "interpersonal",
        "stakeholder",
        "cross-functional",
        "client-facing",
        "present",
        "liaison",
        "collaboration",
    ),
    "analytical": (
        "analytical",
        "analysis",
        "problem solving",
        "problem-solving",
        "root cause",
        "insights",
        "metrics",
        "dashboard",
        "data-driven",
        "requirements analysis",
    ),
    "presales": (
        "presales",
        "pre-sales",
        "pre sales",
        "sales funnel",
        "pipeline",
        "lead generation",
        "prospecting",
        "rfp",
        "crm",
    ),
}


def _soft_skill_supported(requirement_text: str, claims: list[dict]) -> bool:
    req = requirement_text.lower()
    alias_key = None
    for key, aliases in _SOFT_SKILL_ALIASES.items():
        if key in req or any(alias in req for alias in aliases):
            alias_key = key
            break
    if alias_key is None:
        return False
    aliases = _SOFT_SKILL_ALIASES[alias_key]
    for claim in claims:
        if claim.get("kind") not in {
            ClaimKind.project.value,
            ClaimKind.implied_skill.value,
            ClaimKind.other.value,
        }:
            continue
        blob = f"{claim.get('text', '')} {claim.get('quote', '')}".lower()
        if any(alias in blob for alias in aliases):
            return True
    return False


def _infer_category(requirement_text: str, category: RequirementCategory | str | None) -> RequirementCategory | None:
    lowered = (requirement_text or "").lower()
    if "year" in lowered and (
        "experience" in lowered or re.search(r"\d+\s*[-–to]+\s*\d+\s*years?", lowered)
    ):
        return RequirementCategory.experience
    if any(token in lowered for token in ("mba", "bachelor", "degree", "b.tech", "btech", "education")):
        return RequirementCategory.education
    if any(token in lowered for token in ("communication", "interpersonal", "analytical", "problem solving", "presales")):
        return RequirementCategory.soft_skill
    try:
        cat = RequirementCategory(category) if category else None
    except ValueError:
        cat = None
    if cat and cat != RequirementCategory.other:
        return cat
    if len(lowered.split()) <= 3 and lowered.isascii():
        return RequirementCategory.skill
    return cat


def _skill_tokens(requirement_text: str) -> list[str]:
    lowered = requirement_text.lower().strip()
    tokens = [lowered]
    if " or " in lowered:
        tokens.extend(part.strip() for part in lowered.split(" or ") if part.strip())
    return tokens


def _skill_supported(requirement_text: str, profile: dict | None, claims: list[dict]) -> bool:
    tokens = _skill_tokens(requirement_text)
    skills = [str(item).lower() for item in (profile or {}).get("skills_listed") or []]
    summary = str((profile or {}).get("summary") or "").lower()
    for token in tokens:
        if any(token in skill or skill in token for skill in skills):
            return True
        if token in summary:
            return True
        for claim in claims:
            blob = " ".join(
                str(claim.get(key) or "")
                for key in ("text", "quote", "skill_label")
            ).lower()
            if token in blob:
                return True
    return False


def apply_deterministic_overrides(
    flags: DimensionFlags,
    *,
    category: RequirementCategory | str | None,
    requirement_text: str,
    profile: dict | None,
    claims: list[dict],
    supporting_ids: list[str],
) -> DimensionFlags:
    cat = _infer_category(requirement_text, category)

    named = _flag(flags.named)
    applied = _flag(flags.applied)
    professional = _flag(flags.professional)

    if cat == RequirementCategory.education:
        edu_sources = _education_sources(profile, claims)
        if _education_satisfies(requirement_text, edu_sources):
            named = 1
            applied = 1

    if cat == RequirementCategory.experience:
        years = _candidate_years(profile, claims)
        if years is not None and classify_experience_years(requirement_text, years) != "missing":
            named = 1
            professional = 1
            applied = max(applied, 1)

    if cat in {RequirementCategory.soft_skill, RequirementCategory.domain, RequirementCategory.other}:
        if _soft_skill_supported(requirement_text, claims):
            named = 1
            applied = max(applied, 1)
            professional = max(professional, 1)

    return DimensionFlags(
        named=named,
        applied=applied,
        complexity=_flag(flags.complexity),
        professional=professional,
        ownership=_flag(flags.ownership),
        outcome=_flag(flags.outcome),
    )


def candidate_years(profile: dict | None, claims: list[dict]) -> float | None:
    return _candidate_years(profile, claims)


def resolve_requirement_status(
    *,
    requirement_text: str,
    normalized_label: str = "",
    category: RequirementCategory | str | None,
    profile: dict | None,
    claims: list[dict],
    flags: DimensionFlags,
    conflicting: bool = False,
    experience_years: float | None = None,
) -> MatchStatus:
    """Authoritative status: deterministic rules first, LLM flags as fallback."""
    label = (requirement_text or normalized_label).strip()
    cat = _infer_category(label, category)

    if cat == RequirementCategory.education:
        edu_sources = _education_sources(profile, claims)
        return _education_match_status(label, edu_sources)

    if cat == RequirementCategory.experience:
        years = experience_years if experience_years is not None else _candidate_years(profile, claims)
        if years is not None:
            band = classify_experience_years(label, years)
            if band == "matched":
                return MatchStatus.MATCHED
            if band == "partial":
                return MatchStatus.PARTIALLY_MATCHED
            return MatchStatus.MISSING

    if cat in {RequirementCategory.skill, RequirementCategory.tooling}:
        if _skill_supported(label, profile, claims):
            return MatchStatus.MATCHED

    if cat in {RequirementCategory.soft_skill, RequirementCategory.domain, RequirementCategory.other}:
        if _soft_skill_supported(label, claims):
            return MatchStatus.MATCHED

    adjusted = apply_deterministic_overrides(
        flags,
        category=cat or category,
        requirement_text=label,
        profile=profile,
        claims=claims,
        supporting_ids=[],
    )
    return status_from_flags(
        adjusted,
        conflicting=conflicting,
        category=cat or category,
        requirement_text=label,
        profile=profile,
        claims=claims,
        experience_years=experience_years,
    )


def status_from_flags(
    flags: DimensionFlags,
    *,
    conflicting: bool = False,
    category: RequirementCategory | str | None = None,
    requirement_text: str = "",
    profile: dict | None = None,
    claims: list[dict] | None = None,
    experience_years: float | None = None,
) -> MatchStatus:
    if conflicting:
        return MatchStatus.UNCLEAR

    cat = _infer_category(requirement_text, category) if requirement_text else None
    if cat is None:
        try:
            cat = RequirementCategory(category) if category else None
        except ValueError:
            cat = None

    named = _flag(flags.named)
    applied = _flag(flags.applied)

    if cat == RequirementCategory.education:
        edu_sources = _education_sources(profile, claims)
        if edu_sources or named:
            return _education_match_status(requirement_text, edu_sources)
        return MatchStatus.MISSING

    if cat == RequirementCategory.experience:
        years = experience_years
        if years is None and profile is not None and claims is not None:
            years = _candidate_years(profile, claims)
        if years is not None:
            band = classify_experience_years(requirement_text, years)
            if band == "matched":
                return MatchStatus.MATCHED
            if band == "partial":
                return MatchStatus.PARTIALLY_MATCHED
            return MatchStatus.MISSING
        if named and (_flag(flags.professional) or applied):
            return MatchStatus.MATCHED
        if named or applied:
            return MatchStatus.PARTIALLY_MATCHED
        return MatchStatus.MISSING

    if cat == RequirementCategory.soft_skill:
        if named and applied:
            return MatchStatus.MATCHED
        if named or applied:
            return MatchStatus.PARTIALLY_MATCHED
        return MatchStatus.MISSING

    if named and applied and _flag(flags.complexity) and _flag(flags.ownership):
        return MatchStatus.MATCHED
    if named and applied:
        return MatchStatus.PARTIALLY_MATCHED
    if named and not applied:
        return MatchStatus.UNCLEAR
    if not named and applied:
        return MatchStatus.PARTIALLY_MATCHED
    return MatchStatus.MISSING


_CLAIM_KIND_ORDER = {
    ClaimKind.years_claim.value: 0,
    ClaimKind.education.value: 1,
    ClaimKind.skill.value: 2,
    ClaimKind.implied_skill.value: 3,
    ClaimKind.project.value: 4,
    ClaimKind.other.value: 5,
}


def prioritize_claims(claims: list[dict], *, limit: int = 24) -> list[dict]:
    if len(claims) <= limit:
        return claims
    ranked = sorted(
        claims,
        key=lambda claim: (
            _CLAIM_KIND_ORDER.get(str(claim.get("kind") or ""), 9),
            -len(str(claim.get("text") or "")),
        ),
    )
    return ranked[:limit]


def compact_claims(claims: list[dict], *, max_quote: int = 140) -> list[dict]:
    compact: list[dict] = []
    for claim in claims:
        quote = str(claim.get("quote") or "")
        if len(quote) > max_quote:
            quote = quote[: max_quote - 1] + "…"
        text = str(claim.get("text") or "")
        if len(text) > 180:
            text = text[:179] + "…"
        compact.append(
            {
                "id": claim.get("id"),
                "kind": claim.get("kind"),
                "text": text,
                "skill_label": claim.get("skill_label"),
                "years": claim.get("years"),
                "quote": quote,
            }
        )
    return compact


def _compact_profile(profile: dict | None) -> dict:
    if not profile:
        return {}
    return {
        "full_name": profile.get("full_name"),
        "summary": (str(profile.get("summary") or "")[:400] or None),
        "years_experience": profile.get("years_experience"),
        "education": profile.get("education"),
        "roles": profile.get("roles"),
        "skills_listed": profile.get("skills_listed"),
    }


def _batch_size(requirement_count: int, claim_count: int) -> int:
    # Batch requirements when claim volume risks Groq TPM / context limits.
    if claim_count <= 20:
        return requirement_count
    if claim_count > 30:
        return 4
    return 6


async def match_requirements(
    *,
    requirements: list[dict],
    claims: list[dict],
    profile: dict | None,
    config: LLMConfig,
) -> MatcherOutput:
    compact = compact_claims(prioritize_claims(claims))
    slim_profile = _compact_profile(profile)
    batch_size = _batch_size(len(requirements), len(compact))
    if batch_size >= len(requirements):
        user = (
            "Score every requirement against these claims.\n\n"
            f"Profile:\n{slim_profile}\n\n"
            f"Requirements:\n{requirements}\n\n"
            f"Claims:\n{compact}"
        )
        return await complete_json(
            config,
            system=SYSTEM,
            user=user,
            schema=MatcherOutput,
            agent="matcher",
        )

    merged = MatcherOutput()
    for start in range(0, len(requirements), batch_size):
        batch = requirements[start : start + batch_size]
        user = (
            "Score every requirement in this batch against these claims.\n\n"
            f"Profile:\n{slim_profile}\n\n"
            f"Requirements:\n{batch}\n\n"
            f"Claims:\n{compact}"
        )
        part = await complete_json(
            config,
            system=SYSTEM,
            user=user,
            schema=MatcherOutput,
            agent="matcher",
        )
        merged.results.extend(part.results)
        merged.warnings.extend(part.warnings)
    return merged
