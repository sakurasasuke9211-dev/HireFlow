from __future__ import annotations

import asyncio
import logging

from hireflow_api.config import settings

logger = logging.getLogger(__name__)

_arq_pool = None


async def init_queue() -> None:
    global _arq_pool
    if not settings.uses_redis:
        logger.info("Redis unset — extract jobs will run in-process")
        return
    from arq import create_pool
    from arq.connections import RedisSettings

    _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("Redis queue enabled")


async def close_queue() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


async def enqueue_extract(document_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("extract_document", document_id, run_id)
        return
    asyncio.create_task(_run_in_process("extract", document_id, run_id))


async def enqueue_parse(kind: str, subject_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("parse_document", kind, subject_id, run_id)
        return
    asyncio.create_task(_run_in_process("parse", kind, subject_id, run_id))


async def enqueue_match(candidate_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("match_candidate", candidate_id, run_id)
        return
    asyncio.create_task(_run_in_process("match", candidate_id, run_id))


async def enqueue_plan(candidate_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("design_plan", candidate_id, run_id)
        return
    asyncio.create_task(_run_in_process("plan", candidate_id, run_id))


async def enqueue_analyze(transcript_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("analyze_transcript", transcript_id, run_id)
        return
    asyncio.create_task(_run_in_process("analyze", transcript_id, run_id))


async def enqueue_report(candidate_id: str, run_id: str) -> None:
    if _arq_pool is not None:
        await _arq_pool.enqueue_job("generate_report", candidate_id, run_id)
        return
    asyncio.create_task(_run_in_process("report", candidate_id, run_id))


async def _run_in_process(job_type: str, *args: str) -> None:
    try:
        if job_type == "extract":
            from hireflow_api.extract_job import extract_document_job

            await extract_document_job(args[0], args[1])
        elif job_type == "parse":
            from hireflow_api.parse_job import parse_job

            await parse_job(args[0], args[1], args[2])
        elif job_type == "plan":
            from hireflow_api.plan_job import design_plan_job

            await design_plan_job(args[0], args[1])
        elif job_type == "analyze":
            from hireflow_api.transcript_job import analyze_transcript_job

            await analyze_transcript_job(args[0], args[1])
        elif job_type == "report":
            from hireflow_api.report_job import generate_report_job

            await generate_report_job(args[0], args[1])
        else:
            from hireflow_api.match_job import match_candidate_job

            await match_candidate_job(args[0], args[1])
    except Exception:
        logger.exception("in-process %s job failed", job_type)
