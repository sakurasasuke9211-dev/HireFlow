from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, complete_json
from hireflow_domain.enums import FileKind

PROMPT_VERSION = "file_summarizer.v1"

SYSTEM = """You are HireFlow's File Summarizer. Summarize recruiter-facing documents for a hiring workflow.

Rules:
- Use only facts from the provided text. Do not invent requirements, skills, or decisions.
- summary is 2–5 short paragraphs in plain language.
- key_points is 3–8 bullet strings.
- For JD: role, must-haves, nice-to-haves, and ambiguities.
- For resume: background, strongest skills, notable projects, gaps in the document itself.
- For transcript: topics covered, depth shown, shallow areas, and open follow-ups.
- For screening / match and gaps: overall fit, strong matches, and main gaps.
- For interview brief: focus areas and question themes.
- For evidence report: assessment highlights, contradictions, and remaining risks.
- Do not make a hiring decision. Do not say advance, hold, or reject.
"""


class FileSummarizeOutput(BaseModel):
    agent: str = "file_summarizer"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    summary: str
    key_points: list[str] = Field(default_factory=list)


def format_summary(output: FileSummarizeOutput) -> str:
    lines = [output.summary.strip(), ""]
    if output.key_points:
        lines.append("**Key points**")
        lines.extend(f"- {point}" for point in output.key_points)
    return "\n".join(lines).strip()


async def summarize_file(
    text: str,
    config: LLMConfig,
    *,
    kind: FileKind,
    label: str,
) -> FileSummarizeOutput:
    snippet = text if len(text) <= 14000 else text[:14000] + "\n\n[truncated for summarization]"
    return await complete_json(
        config,
        system=SYSTEM,
        user=(
            f"Document kind: {kind.value}\n"
            f"Label: {label}\n\n"
            f"Document:\n{snippet}"
        ),
        schema=FileSummarizeOutput,
        agent="file_summarizer",
    )
