from hireflow_agents.llm import LLMConfig
from hireflow_api.config import settings


def agent_llm_config(agent: str) -> LLMConfig:
    timeout = settings.llm_timeout_seconds
    if agent in {
        "matcher",
        "gap_analyst",
        "interview_designer",
        "transcript_parser",
        "prober",
        "evidence_collector",
        "report",
    }:
        timeout = max(timeout, 120)
    return LLMConfig(
        api_key=settings.resolved_llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_for(agent),
        timeout_seconds=timeout,
        max_retries=settings.llm_max_retries,
        temperature=settings.llm_temperature,
        json_mode=settings.llm_json_mode,
        max_output_tokens=settings.llm_max_output_tokens_for(agent),
    )


def parser_llm_config() -> LLMConfig:
    return agent_llm_config("jd_parser")
