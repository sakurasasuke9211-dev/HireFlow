from hireflow_api.config import settings
from hireflow_api.extract_job import extract_document_job
from hireflow_api.match_job import match_candidate_job
from hireflow_api.parse_job import parse_job
from hireflow_api.plan_job import design_plan_job
from hireflow_api.report_job import generate_report_job
from hireflow_api.transcript_job import analyze_transcript_job


async def extract_document(ctx, document_id: str, run_id: str) -> None:
    await extract_document_job(document_id, run_id)


async def parse_document(ctx, kind: str, subject_id: str, run_id: str) -> None:
    await parse_job(kind, subject_id, run_id)


async def match_candidate(ctx, candidate_id: str, run_id: str) -> None:
    await match_candidate_job(candidate_id, run_id)


async def design_plan(ctx, candidate_id: str, run_id: str) -> None:
    await design_plan_job(candidate_id, run_id)


async def analyze_transcript(ctx, transcript_id: str, run_id: str) -> None:
    await analyze_transcript_job(transcript_id, run_id)


async def generate_report(ctx, candidate_id: str, run_id: str) -> None:
    await generate_report_job(candidate_id, run_id)


class WorkerSettings:
    functions = [extract_document, parse_document, match_candidate, design_plan, analyze_transcript, generate_report]
    redis_settings = None

    def __init__(self) -> None:
        if settings.uses_redis:
            from arq.connections import RedisSettings

            self.redis_settings = RedisSettings.from_dsn(settings.redis_url)
