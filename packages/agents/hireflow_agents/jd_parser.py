from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, complete_json
from hireflow_domain.enums import RequirementCategory, RequirementPriority
from hireflow_domain.schemas import SourceSpan

PROMPT_VERSION = "jd_parser.v1"

SYSTEM = """You are HireFlow's JD Parser. Split a job description into atomic requirements.

Rules:
- One requirement per skill, tool, year-band, domain, or education bar. Never a whole paragraph.
- priority is must_have, nice_to_have, or unclear_priority. If the JD is ambiguous, use unclear_priority and add a warning. Do not guess.
- category is skill, experience, education, domain, tooling, soft_skill, or other.
- Keep source_quote as a verbatim snippet from the JD.
- source_span.quote must match source_quote. Set char_start/char_end if you can locate the quote in the text; otherwise leave them null.
- Do not invent requirements that are not in the JD.
- normalized_label is a short canonical name (e.g. Python, PostgreSQL).
- A must-have Python skill must be its own requirement with normalized_label Python.
"""


class ParsedRequirement(BaseModel):
    text: str
    normalized_label: str
    category: RequirementCategory
    priority: RequirementPriority
    source_quote: str
    source_span: SourceSpan = Field(default_factory=SourceSpan)


class JdParserOutput(BaseModel):
    agent: str = "jd_parser"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    requirements: list[ParsedRequirement] = Field(default_factory=list)


async def parse_jd(text: str, config: LLMConfig, *, filename: str = "jd") -> JdParserOutput:
    return await complete_json(
        config,
        system=SYSTEM,
        user=f"Filename: {filename}\n\nJob description:\n{text}",
        schema=JdParserOutput,
        agent="jd_parser",
    )
