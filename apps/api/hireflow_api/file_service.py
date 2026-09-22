from __future__ import annotations

import logging
import re
import uuid

from hireflow_agents.file_assistant import (
    FileAssistantChatContext as AgentChatContext,
    FileAssistantChatTurn as AgentChatTurn,
    compose_reply,
    context_from_hits,
    resolve_query,
)
from hireflow_agents.file_locator import FileCatalogItem, locate_files as run_file_locator
from hireflow_agents.file_summarizer import format_summary, summarize_file
from hireflow_agents.jd_parser import parse_jd
from hireflow_agents.llm import LLMError
from hireflow_agents.resume_parser import parse_resume
from hireflow_agents.transcript_parser import parse_transcript
from hireflow_api.db import fetch_many, fetch_one, insert_row
from hireflow_api.models import FileAssistantRequest, utcnow
from hireflow_api.llm import agent_llm_config, parser_llm_config
from hireflow_api.models import Candidate, Document, Job, Report
from hireflow_api.services import (
    download_report_file,
    get_interview_plan,
    list_gaps,
    list_matches,
    screening_brief_file,
)
from hireflow_api.storage import get_store
from hireflow_domain.enums import FileAction, FileKind, ReportKind
from hireflow_domain.schemas import (
    EvidenceReportBody,
    FileAssistantChatContext,
    FileAssistantChatRequest,
    FileAssistantChatResponse,
    FileAssistantChatTurn,
    FileAssistantHistoryItem,
    FileAssistantPageContext,
    FileHitPublic,
    FileLocatorResponse,
)

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 12000

KIND_LABELS = {
    FileKind.jd: "Job description",
    FileKind.resume: "Resume",
    FileKind.transcript: "Transcript",
    FileKind.screening_brief: "Match and gaps",
    FileKind.interview_brief: "Interview brief",
    FileKind.evidence: "Evidence report",
}

_MATCH_GAPS_QUERY = re.compile(
    r"\b(match(?:ing)?(?:\s+and|\s*&)?\s*gaps?|gaps?\s+analysis|screening\s+brief|resume\s+evidence|requirement\s+match)\b",
    re.I,
)


def _is_match_gaps_query(query: str) -> bool:
    return bool(_MATCH_GAPS_QUERY.search(query.strip()))


def _candidate_page_hit(
    catalog: list[FileHitPublic],
    *,
    candidate_id: str,
    kind: FileKind,
) -> FileHitPublic | None:
    for item in catalog:
        if item.kind != kind:
            continue
        prefix, _, source_id = item.locator.partition(":")
        if prefix == "screening" and source_id == candidate_id:
            return item
        if prefix == "report" and item.download_path.startswith(f"/candidates/{candidate_id}/"):
            return item
        if item.download_path.startswith(f"/candidates/{candidate_id}/"):
            return item
    return None


def _latest_by_key(rows: list[dict], key_fn, version_key: str = "version") -> list[dict]:
    picked: dict[str, dict] = {}
    for row in rows:
        key = key_fn(row)
        current = picked.get(key)
        if current is None:
            picked[key] = row
            continue
        current_version = int(current.get(version_key) or 0)
        next_version = int(row.get(version_key) or 0)
        if next_version > current_version:
            picked[key] = row
        elif next_version == current_version and str(row.get("created_at") or "") > str(current.get("created_at") or ""):
            picked[key] = row
    return list(picked.values())


def _label(kind: FileKind, job_title: str, candidate_name: str | None) -> str:
    noun = KIND_LABELS[kind]
    if candidate_name:
        return f"{candidate_name} — {job_title} ({noun})"
    return f"{job_title} ({noun})"


async def build_file_catalog(*, org_id: str) -> list[FileHitPublic]:
    jobs = {row["id"]: Job.model_validate(row) for row in await fetch_many("jobs", org_id=org_id)}
    candidates = {
        row["id"]: Candidate.model_validate(row) for row in await fetch_many("candidates", org_id=org_id)
    }
    transcripts = {row["id"]: row for row in await fetch_many("transcripts", org_id=org_id)}
    documents = _latest_by_key(
        await fetch_many("documents", org_id=org_id),
        lambda row: f"{row['owner_type']}:{row['owner_id']}:{row['kind']}",
    )
    reports = _latest_by_key(
        await fetch_many("reports", org_id=org_id),
        lambda row: f"{row['candidate_id']}:{row['kind']}",
    )
    matched_ids = {row["candidate_id"] for row in await fetch_many("match_results", org_id=org_id)}
    hits: list[FileHitPublic] = []

    for row in documents:
        document = Document.model_validate(row)
        job_title = ""
        candidate_name: str | None = None
        if document.kind == "jd":
            job = jobs.get(document.owner_id)
            if job is None:
                continue
            job_title = job.title
            locator = f"document:{document.id}"
            kind = FileKind.jd
            download_path = f"/documents/{document.id}/download"
        elif document.kind == "resume":
            candidate = candidates.get(document.owner_id)
            if candidate is None:
                continue
            job = jobs.get(candidate.job_id)
            job_title = job.title if job else "Role"
            candidate_name = candidate.full_name
            locator = f"document:{document.id}"
            kind = FileKind.resume
            download_path = f"/documents/{document.id}/download"
        elif document.kind == "transcript":
            transcript = transcripts.get(document.owner_id)
            if transcript is None:
                continue
            candidate = candidates.get(transcript["candidate_id"])
            if candidate is None:
                continue
            job = jobs.get(candidate.job_id)
            job_title = job.title if job else "Role"
            candidate_name = candidate.full_name
            locator = f"document:{document.id}"
            kind = FileKind.transcript
            download_path = f"/documents/{document.id}/download"
        else:
            continue
        hits.append(
            FileHitPublic(
                locator=locator,
                kind=kind,
                label=_label(kind, job_title, candidate_name),
                filename=document.original_filename,
                job_title=job_title,
                candidate_name=candidate_name,
                download_path=download_path,
                available=True,
            )
        )

    for candidate in candidates.values():
        job = jobs.get(candidate.job_id)
        job_title = job.title if job else "Role"
        hits.append(
            FileHitPublic(
                locator=f"screening:{candidate.id}",
                kind=FileKind.screening_brief,
                label=_label(FileKind.screening_brief, job_title, candidate.full_name),
                filename=f"{candidate.full_name}-screening-brief.md",
                job_title=job_title,
                candidate_name=candidate.full_name,
                download_path=f"/candidates/{candidate.id}/screening-brief",
                available=candidate.id in matched_ids,
            )
        )

    for row in reports:
        report = Report.model_validate(row)
        candidate = candidates.get(report.candidate_id)
        job = jobs.get(report.job_id)
        job_title = job.title if job else "Role"
        candidate_name = candidate.full_name if candidate else None
        if report.kind == ReportKind.interview_brief.value:
            kind = FileKind.interview_brief
            download_path = f"/candidates/{report.candidate_id}/interview-brief"
        elif report.kind == ReportKind.evidence.value:
            kind = FileKind.evidence
            download_path = f"/reports/{report.id}/download"
        else:
            continue
        hits.append(
            FileHitPublic(
                locator=f"report:{report.id}",
                kind=kind,
                label=_label(kind, job_title, candidate_name),
                filename=report.original_filename,
                job_title=job_title,
                candidate_name=candidate_name,
                download_path=download_path,
                available=True,
            )
        )

    hits.sort(key=lambda item: (item.job_title.lower(), item.candidate_name or "", item.kind.value))
    return hits


async def read_locator_text(*, org_id: str, hit: FileHitPublic) -> str:
    kind_prefix, _, source_id = hit.locator.partition(":")
    if not source_id:
        raise ValueError("Unknown file locator")
    if kind_prefix == "document":
        row = await fetch_one("documents", id=source_id, org_id=org_id)
        if row is None:
            raise KeyError(source_id)
        document = Document.model_validate(row)
        text = (document.extracted_text or "").strip()
        if text:
            return text
        filename, body, mime = await download_document_file(org_id=org_id, document_id=source_id)
        if mime.startswith("text/") or filename.lower().endswith((".txt", ".md", ".vtt")):
            return body.decode("utf-8", errors="replace")
        raise ValueError("Text is not extracted yet. Run extract on this upload first.")
    if kind_prefix == "screening":
        _, body = await screening_brief_file(org_id=org_id, candidate_id=source_id)
        return body.decode("utf-8")
    if kind_prefix == "report":
        _, body, mime = await download_report_file(org_id=org_id, report_id=source_id)
        if mime.startswith("text/") or hit.filename.lower().endswith((".txt", ".md")):
            return body.decode("utf-8", errors="replace")
        return body.decode("utf-8", errors="replace")
    raise ValueError("Unknown file locator")


async def _parse_structured(*, org_id: str, hit: FileHitPublic, text: str) -> tuple[str, dict]:
    kind_prefix, _, source_id = hit.locator.partition(":")
    if hit.kind == FileKind.jd:
        config = parser_llm_config()
        parsed = await parse_jd(text, config, filename=hit.filename)
        payload = parsed.model_dump(mode="json")
        count = len(parsed.requirements)
        return f"Parsed {count} requirement{'s' if count != 1 else ''} from the job description.", payload
    if hit.kind == FileKind.resume:
        config = agent_llm_config("resume_parser")
        parsed = await parse_resume(text, config, filename=hit.filename)
        claims = len(parsed.profile.claims)
        return f"Parsed resume profile with {claims} claim{'s' if claims != 1 else ''}.", parsed.model_dump(mode="json")
    if hit.kind == FileKind.transcript:
        config = agent_llm_config("transcript_parser")
        parsed = await parse_transcript(text, config, candidate_name=hit.candidate_name)
        turns = len(parsed.turns)
        return f"Parsed transcript into {turns} turn{'s' if turns != 1 else ''}.", parsed.model_dump(mode="json")
    if hit.kind == FileKind.screening_brief and kind_prefix == "screening":
        matches = await list_matches(org_id=org_id, candidate_id=source_id)
        gaps = await list_gaps(org_id=org_id, candidate_id=source_id)
        payload = {
            "matches": [item.model_dump(mode="json") for item in matches],
            "gaps": [item.model_dump(mode="json") for item in gaps],
        }
        return f"Structured match and gap data for {hit.candidate_name or 'candidate'}.", payload
    if hit.kind == FileKind.interview_brief and kind_prefix == "report":
        row = await fetch_one("reports", id=source_id, org_id=org_id)
        if row is None:
            raise KeyError(source_id)
        report = Report.model_validate(row)
        plan = await get_interview_plan(org_id=org_id, candidate_id=report.candidate_id)
        questions = []
        if plan.plan:
            questions = [item.model_dump(mode="json") for item in plan.plan.questions]
        payload = {
            "plan": plan.plan.model_dump(mode="json") if plan.plan else None,
            "questions": questions,
        }
        count = len(questions)
        return f"Parsed interview plan with {count} planned question{'s' if count != 1 else ''}.", payload
    if hit.kind == FileKind.evidence and kind_prefix == "report":
        row = await fetch_one("reports", id=source_id, org_id=org_id)
        if row is None:
            raise KeyError(source_id)
        report = Report.model_validate(row)
        if report.body:
            body = EvidenceReportBody.model_validate(report.body)
            return "Structured evidence report.", body.model_dump(mode="json")
        config = agent_llm_config("file_summarizer")
        summarized = await summarize_file(text, config, kind=hit.kind, label=hit.label)
        return "Evidence report text summarized (structured body not stored).", summarized.model_dump(mode="json")
    config = agent_llm_config("file_summarizer")
    summarized = await summarize_file(text, config, kind=hit.kind, label=hit.label)
    return format_summary(summarized), summarized.model_dump(mode="json")


async def _apply_file_action(
    *,
    org_id: str,
    action: FileAction,
    hit: FileHitPublic,
    warnings: list[str],
) -> tuple[str | None, dict | None]:
    if not hit.available:
        raise ValueError("That file is not ready yet. Run the pipeline first.")
    text = await read_locator_text(org_id=org_id, hit=hit)
    if not text.strip():
        raise ValueError("File has no readable text.")
    if action == FileAction.read:
        if len(text) > MAX_READ_CHARS:
            warnings.append("truncated_read")
            excerpt = text[:MAX_READ_CHARS].rstrip() + "\n\n[Truncated — use Download for the full file.]"
        else:
            excerpt = text
        return excerpt, None
    if action == FileAction.summarize:
        try:
            config = agent_llm_config("file_summarizer")
        except Exception as exc:
            raise ValueError("Summarize needs GROQ_API_KEY configured on the API.") from exc
        if not config.api_key:
            raise ValueError("Summarize needs GROQ_API_KEY configured on the API.")
        summarized = await summarize_file(text, config, kind=hit.kind, label=hit.label)
        if summarized.warnings:
            warnings.extend(summarized.warnings)
        return format_summary(summarized), None
    if action == FileAction.parse:
        try:
            intro, payload = await _parse_structured(org_id=org_id, hit=hit, text=text)
        except LLMError as exc:
            raise ValueError("Parse failed — LLM unavailable or returned invalid output.") from exc
        return intro, payload
    return None, None


async def _persist_file_request(
    *,
    org_id: str,
    user_id: str,
    response: FileLocatorResponse,
) -> str | None:
    request_id = str(uuid.uuid4())
    try:
        await insert_row(
            "file_assistant_requests",
            FileAssistantRequest(
                id=request_id,
                org_id=org_id,
                user_id=user_id,
                query=response.query,
                action=response.action.value,
                summary=response.summary,
                primary_locator=response.primary_locator,
                hit_locators=[hit.locator for hit in response.hits],
                warnings=response.warnings,
                answer=response.answer,
                parsed=response.parsed,
                created_at=utcnow(),
            ),
        )
        return request_id
    except Exception:
        logger.exception("file assistant request audit log failed")
        return None


async def list_file_assistant_history(*, org_id: str, limit: int = 12) -> list[FileAssistantHistoryItem]:
    rows = await fetch_many("file_assistant_requests", org_id=org_id, order="created_at", desc=True, limit=limit)
    return [FileAssistantHistoryItem.model_validate(row) for row in rows]


async def locate_org_files(
    *,
    org_id: str,
    user_id: str,
    query: str,
    page_context: FileAssistantPageContext | None = None,
) -> FileLocatorResponse:
    catalog = await build_file_catalog(org_id=org_id)
    trimmed_query = query.strip()
    warnings: list[str] = []
    action = FileAction.locate
    hits: list[FileHitPublic] = []
    summary = ""

    if page_context and page_context.candidate_id and _is_match_gaps_query(trimmed_query):
        hit = _candidate_page_hit(
            catalog,
            candidate_id=page_context.candidate_id,
            kind=FileKind.screening_brief,
        )
        if hit is None:
            name = page_context.candidate_name or "this candidate"
            return FileLocatorResponse(
                query=trimmed_query,
                summary=f"No screening brief found for {name}.",
                action=FileAction.locate,
                want_download=False,
                warnings=["no_page_match"],
                hits=[],
                primary_locator=None,
                answer=(
                    f"I couldn't find match and gap analysis for {name} yet. "
                    "Run resume screening on the candidate page first."
                ),
                parsed=None,
            )
        hits = [hit]
        action = FileAction.read
        want_download = "download" in trimmed_query.lower()
        name = page_context.candidate_name or hit.candidate_name or "this candidate"
        summary = f"Match and gaps for {name}."
    else:
        want_download = False
        config = None
        try:
            config = agent_llm_config("file_locator")
        except Exception:
            config = None
        items = [
            FileCatalogItem(
                locator=item.locator,
                kind=item.kind,
                job_title=item.job_title,
                candidate_name=item.candidate_name,
                filename=item.filename,
                available=item.available,
            )
            for item in catalog
        ]
        try:
            located = await run_file_locator(trimmed_query, items, config)
        except LLMError:
            located = await run_file_locator(trimmed_query, items, None)
        by_locator = {item.locator: item for item in catalog}
        reasons = {item.locator: item.reason for item in located.hits}
        for locator in located.locators:
            item = by_locator.get(locator)
            if item is None:
                continue
            hits.append(item.model_copy(update={"reason": reasons.get(locator, "")}))
        if page_context and page_context.candidate_id:
            scoped = [
                hit
                for hit in hits
                if hit.locator == f"screening:{page_context.candidate_id}"
                or hit.download_path.startswith(f"/candidates/{page_context.candidate_id}/")
            ]
            if scoped:
                hits = scoped
            elif not hits:
                for kind in (FileKind.screening_brief, FileKind.interview_brief, FileKind.evidence):
                    hit = _candidate_page_hit(catalog, candidate_id=page_context.candidate_id, kind=kind)
                    if hit is not None:
                        hits = [hit]
                        break
        warnings = list(located.warnings)
        action = located.action
        summary = located.summary
        want_download = located.want_download
        if page_context and page_context.candidate_id and len(hits) == 1 and _is_match_gaps_query(trimmed_query):
            action = FileAction.read
            want_download = "download" in trimmed_query.lower()
    answer: str | None = None
    parsed: dict | None = None
    primary_locator: str | None = None
    if action in {FileAction.read, FileAction.summarize, FileAction.parse}:
        ready_hits = [hit for hit in hits if hit.available]
        if not ready_hits:
            if hits:
                warnings.append("file_not_ready")
                answer = "The matching file exists but is not ready yet. Run screening or generate the report first."
            else:
                answer = summary or "No matching files found."
        else:
            if len(ready_hits) > 1:
                warnings.append("multiple_matches")
            primary = ready_hits[0]
            primary_locator = primary.locator
            try:
                answer, parsed = await _apply_file_action(
                    org_id=org_id,
                    action=action,
                    hit=primary,
                    warnings=warnings,
                )
            except (KeyError, ValueError) as exc:
                warnings.append("action_failed")
                answer = str(exc)
    response = FileLocatorResponse(
        query=trimmed_query,
        summary=summary,
        action=action,
        want_download=want_download,
        warnings=warnings,
        hits=hits,
        primary_locator=primary_locator,
        answer=answer,
        parsed=parsed,
    )
    response.request_id = await _persist_file_request(org_id=org_id, user_id=user_id, response=response)
    return response


def _agent_turn(turn: FileAssistantChatTurn) -> AgentChatTurn:
    context = None
    if turn.context is not None:
        context = AgentChatContext.model_validate(turn.context.model_dump())
    return AgentChatTurn(role=turn.role, content=turn.content, context=context)


async def chat_with_assistant(
    *,
    org_id: str,
    user_id: str,
    body: FileAssistantChatRequest,
) -> FileAssistantChatResponse:
    if body.messages[-1].role != "user":
        raise ValueError("The last message must be from the recruiter")
    agent_turns = [_agent_turn(turn) for turn in body.messages]
    query = resolve_query(agent_turns)
    result = await locate_org_files(
        org_id=org_id,
        user_id=user_id,
        query=query,
        page_context=body.page_context,
    )
    hit_dicts = [hit.model_dump(mode="json") for hit in result.hits]
    reply = compose_reply(
        user_message=body.messages[-1].content,
        action=result.action,
        summary=result.summary,
        hits=hit_dicts,
        answer=result.answer,
        want_download=result.want_download,
    )
    ctx = context_from_hits(hit_dicts, primary_locator=result.primary_locator)
    domain_ctx = FileAssistantChatContext.model_validate(ctx.model_dump()) if ctx else None
    payload = result.model_dump()
    payload.pop("reply", None)
    payload.pop("context", None)
    return FileAssistantChatResponse(
        **payload,
        reply=reply,
        context=domain_ctx,
    )


async def download_located_file(*, org_id: str, locator: str) -> tuple[str, bytes, str]:
    kind, _, source_id = locator.partition(":")
    if not source_id:
        raise ValueError("Unknown file locator")
    if kind == "document":
        return await download_document_file(org_id=org_id, document_id=source_id)
    if kind == "screening":
        filename, body = await screening_brief_file(org_id=org_id, candidate_id=source_id)
        return filename, body, "text/markdown"
    if kind == "report":
        return await download_report_file(org_id=org_id, report_id=source_id)
    raise ValueError("Unknown file locator")


async def download_document_file(*, org_id: str, document_id: str) -> tuple[str, bytes, str]:
    row = await fetch_one("documents", id=document_id, org_id=org_id)
    if row is None:
        raise KeyError(document_id)
    document = Document.model_validate(row)
    body = await get_store().get(document.storage_key)
    if not body:
        raise ValueError("Original file is not available")
    return document.original_filename, body, document.mime or "application/octet-stream"
