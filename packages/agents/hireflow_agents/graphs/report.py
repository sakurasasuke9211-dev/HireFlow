"""Report graph — Evidence Collector then Report Agent. Decision is human-only."""

from hireflow_agents.evidence_collector import EvidenceCollectorOutput, collect_evidence
from hireflow_agents.llm import LLMConfig
from hireflow_agents.report import ReportAgentOutput, write_report


async def run_collect_evidence(
    *,
    requirements: list[dict],
    matches: list[dict],
    claims: list[dict],
    probes: list[dict],
    turns: list[dict],
    config: LLMConfig,
) -> EvidenceCollectorOutput:
    return await collect_evidence(
        requirements=requirements,
        matches=matches,
        claims=claims,
        probes=probes,
        turns=turns,
        config=config,
    )


async def run_write_report(
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
    return await write_report(
        candidate_name=candidate_name,
        job_title=job_title,
        partial=partial,
        matrix=matrix,
        evidence=evidence,
        unresolved=unresolved,
        contradictions=contradictions,
        config=config,
    )
