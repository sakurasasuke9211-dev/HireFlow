"""Transcript graph — Parser then Prober. No live interviewer."""

from hireflow_agents.llm import LLMConfig
from hireflow_agents.prober import ProberOutput, probe_transcript
from hireflow_agents.transcript_parser import TranscriptParserOutput, parse_transcript


async def run_transcript_parse(
    text: str,
    config: LLMConfig,
    *,
    candidate_name: str | None = None,
    requirements: list[dict] | None = None,
    questions: list[dict] | None = None,
) -> TranscriptParserOutput:
    return await parse_transcript(
        text,
        config,
        candidate_name=candidate_name,
        requirements=requirements,
        questions=questions,
    )


async def run_probe(
    *,
    requirements: list[dict],
    turns: list[dict],
    config: LLMConfig,
) -> ProberOutput:
    return await probe_transcript(requirements=requirements, turns=turns, config=config)
