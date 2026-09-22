from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, complete_json
from hireflow_domain.enums import ClaimKind
from hireflow_domain.schemas import SourceSpan

PROMPT_VERSION = "resume_parser.v2"

SYSTEM = """You are HireFlow's Resume Parser. Turn a resume into a profile plus claims.

Rules:
- Extract identity, work history, projects, education, and the skills list.
- Every skill and every project/work bullet becomes a Claim.
- kind is skill | implied_skill | years_claim | project | education | other.
- Skills listed only in a skills section are kind=skill.
- Skills used in a bullet but not listed as a dedicated skill are implied_skill.
- Years-only lines such as "Python — 4 years" or "Python - 4 years" MUST be years_claim with skill_label=Python and years=4.

Experience extraction (critical):
- Set profile.years_experience to total professional tenure in years (decimal OK, e.g. 2.5).
- Compute from BOTH: (1) explicit statements in the intro/summary/header (e.g. "2+ years", "3 years of experience"), AND (2) employment date ranges on the right of each role (sum overlapping full-time roles; round to one decimal).
- Emit a years_claim with skill_label="Professional experience", text describing total years, years=profile.years_experience, and a quote from the intro or computed from role dates.
- Each employment entry MUST become at least one kind=project claim quoting the role bullet(s). Include employer name and dates in the claim text when present.

Education extraction (critical):
- Populate profile.education with each degree (e.g. "MBA, IIM Indore", "B.Tech, Delhi Technological University").
- Each degree MUST also be kind=education with verbatim quote from the resume.

Soft skills and domain evidence:
- Stakeholder management, cross-functional work, client engagement, and presenting → kind=project or implied_skill claims (not only skills list).
- Analytical work (data analysis, dashboards, root cause, requirements analysis, metrics, problem solving) → kind=project claims from the relevant bullets.
- Presales / sales funnel / pipeline / CRM / lead generation from internships or jobs → kind=project claims quoting that bullet.

Do not output match statuses. Do not say MATCHED.
- quote and source_span.quote are verbatim resume text.
- Set char_start/char_end when you can locate the quote; otherwise null.
- parser_warnings for missing sections or ambiguous identity.
"""


class ParsedClaim(BaseModel):
    kind: ClaimKind
    text: str
    skill_label: str | None = None
    years: float | None = None
    quote: str
    source_span: SourceSpan = Field(default_factory=SourceSpan)


class ParsedProfile(BaseModel):
    full_name: str | None = None
    email: str | None = None
    summary: str | None = None
    years_experience: float | None = None
    education: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    skills_listed: list[str] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)
    claims: list[ParsedClaim] = Field(default_factory=list)


class ResumeParserOutput(BaseModel):
    agent: str = "resume_parser"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    profile: ParsedProfile


_MAX_RESUME_CHARS = 12_000


def _trim_resume_text(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    cleaned = text.strip()
    if len(cleaned) <= _MAX_RESUME_CHARS:
        return cleaned, warnings
    head = _MAX_RESUME_CHARS // 2
    tail = _MAX_RESUME_CHARS - head
    trimmed = cleaned[:head] + "\n\n[... middle omitted for size ...]\n\n" + cleaned[-tail:]
    warnings.append("Resume text was trimmed before parsing to stay within model limits.")
    return trimmed, warnings


async def parse_resume(text: str, config: LLMConfig, *, filename: str = "resume") -> ResumeParserOutput:
    trimmed, trim_warnings = _trim_resume_text(text)
    parsed = await complete_json(
        config,
        system=SYSTEM,
        user=f"Filename: {filename}\n\nResume:\n{trimmed}",
        schema=ResumeParserOutput,
        agent="resume_parser",
    )
    if trim_warnings:
        parsed.warnings = [*trim_warnings, *parsed.warnings]
        parsed.profile.parser_warnings = [*trim_warnings, *parsed.profile.parser_warnings]
    return parsed
