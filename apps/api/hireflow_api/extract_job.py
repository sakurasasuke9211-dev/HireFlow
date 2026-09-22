from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid

from hireflow_api.db import fetch_one, insert_row, update_rows
from hireflow_api.models import AgentTrace, Document, PipelineRun, utcnow
from hireflow_api.storage import get_store
from hireflow_extract import ExtractionError, extract_text

logger = logging.getLogger(__name__)


async def extract_document_job(document_id: str, run_id: str) -> None:
    run_row = await fetch_one("pipeline_runs", id=run_id)
    document_row = await fetch_one("documents", id=document_id)
    if run_row is None or document_row is None:
        logger.error("extract job missing run or document: %s %s", run_id, document_id)
        return

    run = PipelineRun.model_validate(run_row)
    document = Document.model_validate(document_row)
    await update_rows(
        "pipeline_runs",
        {"status": "running", "started_at": utcnow()},
        id=run.id,
    )

    started = time.perf_counter()
    input_payload = {
        "document_id": document.id,
        "filename": document.original_filename,
        "mime": document.mime,
        "sha256": document.sha256,
    }
    extracted_text = None
    error = None
    status = "succeeded"
    output_payload: dict
    try:
        content = await get_store().get(document.storage_key)
        extracted_text = await asyncio.to_thread(
            extract_text,
            content,
            filename=document.original_filename,
            mime=document.mime,
        )
        output_payload = {"chars": len(extracted_text), "ok": True}
    except ExtractionError as exc:
        status = "failed"
        error = str(exc)
        output_payload = {"ok": False, "error": str(exc)}
    except Exception:
        logger.exception("extract job failed")
        status = "failed"
        error = "could not read file"
        output_payload = {"ok": False, "error": "could not read file"}

    await update_rows(
        "documents",
        {"extracted_text": extracted_text},
        id=document.id,
    )
    await update_rows(
        "pipeline_runs",
        {"status": status, "error": error, "finished_at": utcnow()},
        id=run.id,
    )
    await insert_row(
        "agent_traces",
        AgentTrace(
            id=str(uuid.uuid4()),
            org_id=run.org_id,
            run_id=run.id,
            agent="text_extract",
            schema_version="1.0",
            model=None,
            prompt_version=None,
            input_hash=hashlib.sha256(json.dumps(input_payload, sort_keys=True).encode()).hexdigest(),
            input_json=input_payload,
            output_json=output_payload,
            token_usage=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
    if status == "succeeded":
        from hireflow_api.services import continue_after_extract

        await continue_after_extract(document=document)
