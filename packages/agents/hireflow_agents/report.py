from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json

PROMPT_VERSION = "report.v1"
CLOSING = "HireFlow does not hire; the recruiter decides."

SYSTEM = """You are HireFlow's Report Agent. Write a recruiter-facing assessment only from the provided EvidenceItem rows.

Rules:
- No new facts. If evidence is missing, say so.
- Cite evidence with the provided codes (E1, E2). Never use UUIDs.
- Remaining follow-ups are unvalidated gaps, not a live interview script.
- Include remaining risks. Do not output advance, hold, or reject.
- Always include: HireFlow does not hire; the recruiter decides.
- headline is one or two sentences answering whether the candidate's evidence validates the JD.
"""


class ReportAgentOutput(BaseModel):
    agent: str = "report"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    headline: str
    remaining_risks: list[str] = Field(default_factory=list)
    closing: str = CLOSING


def fallback_report(
    *,
    candidate_name: str,
    job_title: str,
    partial: bool,
    matrix: list[dict],
    unresolved: list[dict],
    contradictions: list[dict],
) -> ReportAgentOutput:
    matched = sum(1 for row in matrix if row.get("final") == "MATCHED")
    unclear = [row for row in matrix if row.get("unvalidated") or row.get("final") in {"UNCLEAR", "MISSING", "PARTIALLY_MATCHED"}]
    if partial:
        headline = (
            f"{candidate_name} has resume evidence for {job_title}, but there is no interview transcript yet. "
            "Interview columns are empty."
        )
    else:
        headline = (
            f"{candidate_name} for {job_title}: {matched} of {len(matrix)} requirements are MATCHED after resume and transcript. "
            "Status changes cite the evidence codes below."
        )
    risks: list[str] = []
    if partial:
        risks.append("This is a partial report. Upload and analyze a transcript before treating interview coverage as proven.")
    for row in contradictions:
        risks.append(f"Contradiction on {row.get('requirement_label')}: {row.get('interpretation') or row.get('quote')}")
    for row in unresolved:
        label = row.get("requirement_label") or "a requirement"
        risks.append(f"Unvalidated gap on {label}.")
    if not risks and unclear:
        risks.append("Some must-haves still lack applied, ownership, or outcome evidence.")
    if not risks:
        risks.append("No outstanding evidence risks were recorded. The recruiter still decides.")
    return ReportAgentOutput(headline=headline, remaining_risks=risks[:8], closing=CLOSING)


async def write_report(
    *,
    candidate_name: str,
    job_title: str,
    partial: bool,
    matrix: list[dict],
    evidence: list[dict],
    unresolved: list[dict],
    contradictions: list[dict],
    config: LLMConfig,
) -> ReportAgentOutput:
    fallback = fallback_report(
        candidate_name=candidate_name,
        job_title=job_title,
        partial=partial,
        matrix=matrix,
        unresolved=unresolved,
        contradictions=contradictions,
    )
    try:
        parsed = await complete_json(
            config,
            system=SYSTEM,
            user=(
                "Write headline and remaining risks only from this evidence pack.\n\n"
                f"Candidate: {candidate_name}\nRole: {job_title}\nPartial: {partial}\n\n"
                f"Matrix:\n{matrix}\n\n"
                f"Evidence:\n{evidence}\n\n"
                f"Unresolved:\n{unresolved}\n\n"
                f"Contradictions:\n{contradictions}"
            ),
            schema=ReportAgentOutput,
            agent="report",
        )
    except LLMError:
        return fallback
    headline = (parsed.headline or "").strip() or fallback.headline
    risks = [item.strip() for item in parsed.remaining_risks if item.strip()] or fallback.remaining_risks
    closing = CLOSING
    warnings = list(parsed.warnings)
    lowered = headline.lower()
    if "advance" in lowered or "reject" in lowered or "hire them" in lowered:
        headline = fallback.headline
        warnings.append("Hiring language was removed from the report headline.")
    return ReportAgentOutput(headline=headline, remaining_risks=risks[:8], closing=closing, warnings=warnings)
