from __future__ import annotations

from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json
from hireflow_agents.matcher import status_from_flags
from hireflow_agents.prober import is_years_only, related_turns
from hireflow_domain.enums import (
    ClaimKind,
    EvidenceDimension,
    EvidenceSource,
    EvidenceStrength,
    MatchStatus,
    ProbeVerdict,
)
from hireflow_domain.schemas import DimensionFlags

PROMPT_VERSION = "evidence_collector.v1"
DIMENSIONS = [item.value for item in EvidenceDimension]

SYSTEM = """You are HireFlow's Evidence Collector. Attach quotes to each JD requirement from resume claims and transcript turns.

Rules:
- Use only the provided claims and turns. Do not invent quotes.
- strength is strong | weak | none.
- Years-only claims and years-only transcript answers are weak, never strong.
- Prober verdicts are hints, not proof. Still attach the quote.
- status_after_interview uses MATCHED | PARTIALLY_MATCHED | MISSING | UNCLEAR. Null if there is no transcript.
- Not discussed: leave resume status unchanged and mark unvalidated.
- Confirmed missing stays MISSING. Contradiction becomes UNCLEAR.
- Do not write a hiring decision.
- Do not include claim IDs or UUIDs in interpretation.
"""


class CollectedItem(BaseModel):
    requirement_id: str
    source: str
    quote: str
    source_ref: str | None = None
    interpretation: str = ""
    strength: str = EvidenceStrength.weak.value
    dimensions_supported: list[str] = Field(default_factory=list)
    contradicts_claim_id: str | None = None


class RequirementStatus(BaseModel):
    requirement_id: str
    status_after_interview: str | None = None
    unvalidated: bool = False
    remaining_doubt: str = ""


class EvidenceCollectorOutput(BaseModel):
    agent: str = "evidence_collector"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    items: list[CollectedItem] = Field(default_factory=list)
    statuses: list[RequirementStatus] = Field(default_factory=list)


def _flag(value: int | bool) -> int:
    return 1 if int(value) else 0


def _flags(raw: dict | None) -> DimensionFlags:
    data = raw or {}
    return DimensionFlags(
        named=_flag(data.get("named") or 0),
        applied=_flag(data.get("applied") or 0),
        complexity=_flag(data.get("complexity") or 0),
        professional=_flag(data.get("professional") or 0),
        ownership=_flag(data.get("ownership") or 0),
        outcome=_flag(data.get("outcome") or 0),
    )


def _merge(resume: DimensionFlags, interview: DimensionFlags) -> DimensionFlags:
    return DimensionFlags(
        named=max(_flag(resume.named), _flag(interview.named)),
        applied=max(_flag(resume.applied), _flag(interview.applied)),
        complexity=max(_flag(resume.complexity), _flag(interview.complexity)),
        professional=max(_flag(resume.professional), _flag(interview.professional)),
        ownership=max(_flag(resume.ownership), _flag(interview.ownership)),
        outcome=max(_flag(resume.outcome), _flag(interview.outcome)),
    )


def interview_flags(verdict: ProbeVerdict | None, missing: list[str], text: str) -> DimensionFlags:
    if verdict is None or verdict in {ProbeVerdict.not_discussed, ProbeVerdict.confirmed_missing}:
        return DimensionFlags()
    named = 1
    applied = 1 if verdict == ProbeVerdict.sufficient else 0
    if verdict == ProbeVerdict.shallow or is_years_only(text):
        applied = 0
    missing_set = {item for item in missing if item in DIMENSIONS}
    def present(name: str) -> int:
        if not applied:
            return 0
        return 0 if name in missing_set else 1
    return DimensionFlags(
        named=named,
        applied=applied,
        complexity=present("complexity"),
        professional=present("professional"),
        ownership=present("ownership"),
        outcome=present("outcome"),
    )


def status_after_interview(
    *,
    resume_status: MatchStatus,
    verdict: ProbeVerdict | None,
    merged: DimensionFlags,
    transcript_text: str,
) -> tuple[MatchStatus | None, bool]:
    if verdict is None:
        return None, resume_status != MatchStatus.MATCHED
    if verdict == ProbeVerdict.not_discussed:
        return resume_status, True
    if verdict == ProbeVerdict.confirmed_missing:
        return MatchStatus.MISSING, False
    if verdict == ProbeVerdict.contradiction:
        return MatchStatus.UNCLEAR, False
    proposed = status_from_flags(merged, conflicting=False)
    if verdict == ProbeVerdict.shallow and is_years_only(transcript_text):
        if resume_status == MatchStatus.PARTIALLY_MATCHED:
            return MatchStatus.PARTIALLY_MATCHED, True
        return MatchStatus.UNCLEAR, True
    if verdict == ProbeVerdict.shallow and proposed == MatchStatus.MATCHED:
        proposed = MatchStatus.PARTIALLY_MATCHED
    return proposed, proposed != MatchStatus.MATCHED


def _strength_resume(claim: dict, flags: DimensionFlags) -> EvidenceStrength:
    kind = str(claim.get("kind") or "")
    if kind == ClaimKind.years_claim.value or not _flag(flags.applied):
        return EvidenceStrength.weak
    if _flag(flags.applied) and (_flag(flags.complexity) or _flag(flags.ownership)):
        return EvidenceStrength.strong
    return EvidenceStrength.weak


def _strength_interview(verdict: ProbeVerdict | None, text: str) -> EvidenceStrength:
    if verdict == ProbeVerdict.sufficient and not is_years_only(text):
        return EvidenceStrength.strong
    if verdict in {ProbeVerdict.shallow, ProbeVerdict.contradiction}:
        return EvidenceStrength.weak
    return EvidenceStrength.none


def _dims(flags: DimensionFlags) -> list[str]:
    return [name for name in DIMENSIONS if _flag(getattr(flags, name))]


def fallback_collect(
    *,
    requirements: list[dict],
    matches: list[dict],
    claims: list[dict],
    probes: list[dict],
    turns: list[dict],
) -> EvidenceCollectorOutput:
    claims_by_id = {str(item.get("id")): item for item in claims if item.get("id")}
    probe_by_req = {str(item.get("requirement_id")): item for item in probes}
    items: list[CollectedItem] = []
    statuses: list[RequirementStatus] = []
    has_transcript = bool(probes or turns)
    warnings: list[str] = []
    if not has_transcript:
        warnings.append("No analyzed transcript. This is a partial report; interview columns are empty.")

    for requirement in requirements:
        req_id = str(requirement["id"])
        label = str(requirement.get("label") or "this requirement")
        match = next((item for item in matches if str(item.get("requirement_id")) == req_id), None)
        resume_status = MatchStatus(match["status"]) if match and match.get("status") else MatchStatus.MISSING
        resume_flags = _flags((match or {}).get("dimension_flags"))
        supporting_ids = list((match or {}).get("supporting_claim_ids") or [])
        probe = probe_by_req.get(req_id)
        verdict = None
        if probe:
            try:
                verdict = ProbeVerdict(probe.get("verdict"))
            except ValueError:
                verdict = ProbeVerdict.not_discussed
        related = related_turns({"id": req_id, "label": label}, turns) if turns else []
        interview_text = " ".join(str(turn.get("text") or "") for turn in related)
        missing = list((probe or {}).get("missing_dimensions") or [])
        i_flags = interview_flags(verdict, missing, interview_text)
        merged = _merge(resume_flags, i_flags) if has_transcript else resume_flags
        after, unvalidated = status_after_interview(
            resume_status=resume_status,
            verdict=verdict if has_transcript else None,
            merged=merged,
            transcript_text=interview_text,
        )
        doubt = ""
        if not has_transcript:
            doubt = "Interview evidence has not been collected."
        elif verdict == ProbeVerdict.not_discussed:
            doubt = f"{label} was not discussed. Resume status is unvalidated."
        elif verdict == ProbeVerdict.shallow:
            doubt = f"Transcript coverage of {label} is shallow. Years are not proof."
        elif verdict == ProbeVerdict.confirmed_missing:
            doubt = f"The candidate confirmed they have not used {label}."
        elif verdict == ProbeVerdict.contradiction:
            doubt = f"The transcript contradicts the resume on {label}."
        elif after != MatchStatus.MATCHED:
            missing_dims = [name for name in DIMENSIONS if not _flag(getattr(merged, name))]
            if missing_dims:
                doubt = "Still missing: " + ", ".join(missing_dims) + "."
        statuses.append(
            RequirementStatus(
                requirement_id=req_id,
                status_after_interview=after.value if after else None,
                unvalidated=unvalidated,
                remaining_doubt=doubt,
            )
        )

        added_resume = False
        for claim_id in supporting_ids:
            claim = claims_by_id.get(str(claim_id))
            if claim is None:
                continue
            quote = str(claim.get("quote") or claim.get("text") or "").strip()
            if not quote:
                continue
            items.append(
                CollectedItem(
                    requirement_id=req_id,
                    source=EvidenceSource.resume.value,
                    quote=quote,
                    source_ref=str(claim_id),
                    interpretation=f"Resume claim for {label}.",
                    strength=_strength_resume(claim, resume_flags).value,
                    dimensions_supported=_dims(resume_flags),
                )
            )
            added_resume = True
        if not added_resume:
            for quote in (match or {}).get("quotes") or []:
                text = str(quote).strip()
                if not text:
                    continue
                items.append(
                    CollectedItem(
                        requirement_id=req_id,
                        source=EvidenceSource.resume.value,
                        quote=text,
                        interpretation=f"Resume mention of {label}.",
                        strength=EvidenceStrength.weak.value if resume_status != MatchStatus.MISSING else EvidenceStrength.none.value,
                        dimensions_supported=_dims(resume_flags),
                    )
                )
                added_resume = True
                break
        if not added_resume:
            items.append(
                CollectedItem(
                    requirement_id=req_id,
                    source=EvidenceSource.resume.value,
                    quote="No evidence found",
                    interpretation=f"No resume evidence for {label}.",
                    strength=EvidenceStrength.none.value,
                )
            )

        if has_transcript:
            turn_ids = list((probe or {}).get("supporting_turn_ids") or [])
            used_turns = [turn for turn in related if str(turn.get("id")) in {str(item) for item in turn_ids}] or related[:2]
            if verdict == ProbeVerdict.not_discussed or not used_turns:
                items.append(
                    CollectedItem(
                        requirement_id=req_id,
                        source=EvidenceSource.interview.value,
                        quote="No evidence found",
                        interpretation=f"{label} was not discussed in the transcript." if verdict == ProbeVerdict.not_discussed else f"No interview quote for {label}.",
                        strength=EvidenceStrength.none.value,
                    )
                )
            else:
                first_claim = supporting_ids[0] if supporting_ids else None
                for turn in used_turns:
                    quote = str(turn.get("text") or "").strip()
                    if not quote:
                        continue
                    items.append(
                        CollectedItem(
                            requirement_id=req_id,
                            source=EvidenceSource.interview.value,
                            quote=quote,
                            source_ref=str(turn.get("id") or "") or None,
                            interpretation=f"Transcript coverage of {label} is {verdict.value.replace('_', ' ') if verdict else 'unscored'}.",
                            strength=_strength_interview(verdict, quote).value,
                            dimensions_supported=_dims(i_flags),
                            contradicts_claim_id=first_claim if verdict == ProbeVerdict.contradiction else None,
                        )
                    )

    if any(item.status_after_interview == MatchStatus.UNCLEAR.value for item in statuses):
        warnings.append("Some requirements remain UNCLEAR after the interview.")
    return EvidenceCollectorOutput(warnings=warnings, items=items, statuses=statuses)


def _overlay_interpretations(base: EvidenceCollectorOutput, parsed: EvidenceCollectorOutput) -> EvidenceCollectorOutput:
    by_key = {
        (item.requirement_id, item.source, (item.quote or "")[:80]): item.interpretation
        for item in parsed.items
        if item.interpretation
    }
    merged_items = []
    for item in base.items:
        key = (item.requirement_id, item.source, (item.quote or "")[:80])
        interpretation = by_key.get(key) or item.interpretation
        merged_items.append(item.model_copy(update={"interpretation": interpretation}))
    warnings = list(base.warnings)
    for warning in parsed.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return EvidenceCollectorOutput(warnings=warnings, items=merged_items, statuses=base.statuses)


async def collect_evidence(
    *,
    requirements: list[dict],
    matches: list[dict],
    claims: list[dict],
    probes: list[dict],
    turns: list[dict],
    config: LLMConfig,
) -> EvidenceCollectorOutput:
    fallback = fallback_collect(
        requirements=requirements,
        matches=matches,
        claims=claims,
        probes=probes,
        turns=turns,
    )
    try:
        parsed = await complete_json(
            config,
            system=SYSTEM,
            user=(
                "Attach quotes and interpretations. Do not invent evidence. Do not decide hire.\n\n"
                f"Requirements:\n{requirements}\n\n"
                f"Matches:\n{matches}\n\n"
                f"Claims:\n{claims}\n\n"
                f"Probes:\n{probes}\n\n"
                f"Turns:\n{turns}"
            ),
            schema=EvidenceCollectorOutput,
            agent="evidence_collector",
        )
    except LLMError:
        return fallback
    return _overlay_interpretations(fallback, parsed)
