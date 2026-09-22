"""Screening graph — Phase 3 adds Interview Designer after match and gaps."""

from hireflow_agents.gap_analyst import GapAnalystOutput, analyze_gaps
from hireflow_agents.interview_designer import InterviewDesignerOutput, design_interview_plan
from hireflow_agents.jd_parser import JdParserOutput, parse_jd
from hireflow_agents.llm import LLMConfig
from hireflow_agents.matcher import MatcherOutput, match_requirements
from hireflow_agents.resume_parser import ResumeParserOutput, parse_resume


async def run_jd_parse(text: str, config: LLMConfig, *, filename: str) -> JdParserOutput:
    return await parse_jd(text, config, filename=filename)


async def run_resume_parse(text: str, config: LLMConfig, *, filename: str) -> ResumeParserOutput:
    return await parse_resume(text, config, filename=filename)


async def run_match(
    *,
    requirements: list[dict],
    claims: list[dict],
    profile: dict | None,
    config: LLMConfig,
) -> MatcherOutput:
    return await match_requirements(
        requirements=requirements,
        claims=claims,
        profile=profile,
        config=config,
    )


async def run_gaps(*, matches: list[dict], config: LLMConfig) -> GapAnalystOutput:
    return await analyze_gaps(matches=matches, config=config)


async def run_interview_plan(
    *,
    gaps: list[dict],
    profile: dict | None,
    config: LLMConfig,
) -> InterviewDesignerOutput:
    return await design_interview_plan(gaps=gaps, profile=profile, config=config)
