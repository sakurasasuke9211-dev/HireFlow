from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, complete_json
from hireflow_domain.enums import GapSeverity, MatchStatus, RequirementPriority

PROMPT_VERSION = "gap_analyst.v1"

SYSTEM = """You are HireFlow's Gap Analyst. Turn non-MATCHED requirements into interview investigation goals.

Rules:
- Every non-MATCHED must_have MUST have a gap. Missing is not a reject.
- Nice-to-haves only get a gap when the gap is worth interview time (medium+).
- severity is blocker | high | medium | low.
- MISSING must-haves are high (blocker only if the JD clearly cannot proceed without it).
- UNCLEAR must-haves are high. PARTIALLY_MATCHED must-haves are medium unless depth is almost absent.
- investigation_goal is one sentence the interview must answer.
- suggested_probe_themes are short labels such as "artifact built", "complexity", "ownership", "outcome".
- Do not write interview questions. Do not set deal_breaker or skip_probe.
- Do not invent MATCHED requirements as gaps.
"""


class GapItem(BaseModel):
    requirement_id: str
    severity: GapSeverity
    investigation_goal: str
    suggested_probe_themes: list[str] = Field(default_factory=list)


class GapAnalystOutput(BaseModel):
    agent: str = "gap_analyst"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)


def default_severity(status: MatchStatus, priority: str) -> GapSeverity:
    if priority == RequirementPriority.must_have.value:
        if status == MatchStatus.MISSING:
            return GapSeverity.high
        if status == MatchStatus.UNCLEAR:
            return GapSeverity.high
        return GapSeverity.medium
    if status == MatchStatus.MISSING:
        return GapSeverity.medium
    return GapSeverity.low


def default_goal(label: str, status: MatchStatus) -> str:
    if status == MatchStatus.MISSING:
        return f"Establish whether the candidate has used {label} professionally, and if so on what system."
    if status == MatchStatus.UNCLEAR:
        return f"Prove professional {label}: system built, complexity, personal contribution, measurable outcome."
    return f"Fill the missing depth on {label}: complexity, ownership, and outcome."


def default_themes(status: MatchStatus) -> list[str]:
    if status == MatchStatus.MISSING:
        return ["professional use", "artifact built"]
    return ["artifact built", "complexity", "ownership", "outcome"]


async def analyze_gaps(
    *,
    matches: list[dict],
    config: LLMConfig,
) -> GapAnalystOutput:
    return await complete_json(
        config,
        system=SYSTEM,
        user=(
            "Create gaps for these match results. Skip MATCHED rows.\n\n"
            f"Matches:\n{matches}"
        ),
        schema=GapAnalystOutput,
        agent="gap_analyst",
    )
