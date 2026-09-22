from __future__ import annotations

import json
import re
from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json
from hireflow_domain.enums import FileAction, FileKind

PROMPT_VERSION = "file_locator.v2"

SYSTEM = """You are HireFlow's File Locator. Pick files from the catalog that match the recruiter's request.

Rules:
- Return only locators that appear in the catalog. Never invent files or locators.
- action is one of: locate, download, read, summarize, parse.
  - download: they asked to download, save, export, or fetch the file bytes.
  - read: they asked to read, show, open, display, or view the contents.
  - summarize: they asked for a summary, overview, tldr, or recap.
  - parse: they asked to parse, extract, structure, or break down the file.
  - locate: find/list only (default when unclear).
- want_download is true only when action is download.
- If they named a person or role, prefer files for that person or role.
- Kind hints: JD / job description → jd; resume / CV → resume; transcript → transcript; match / gaps / screening → screening_brief; interview brief / questions / plan → interview_brief; evidence / final report / assessment → evidence.
- If the kind is missing, return the most likely files for the named person or role (cap 8).
- If nothing matches, locators is empty and summary explains that in one sentence.
- Do not mention Decision. You do not hire. You only find files.
"""

_KIND_PHRASES: dict[FileKind, tuple[str, ...]] = {
    FileKind.jd: ("job description", "job desc", " jd ", "the jd"),
    FileKind.resume: ("resume", " cv ", "curriculum"),
    FileKind.transcript: ("transcript", "interview notes", "call notes"),
    FileKind.screening_brief: ("screening", "match and gaps", "match & gaps", "gaps", "match analysis"),
    FileKind.interview_brief: (
        "interview brief",
        "interview plan",
        "interview question",
        "planned question",
        "question list",
    ),
    FileKind.evidence: ("evidence report", "evidence", "final report", "assessment report"),
}

_DOWNLOAD_WORDS = ("download", "fetch", "save", "export", "give me the file", "send me the file", "pull the file")
_READ_WORDS = (
    "read",
    "show me",
    "show the",
    "open",
    "display",
    "view",
    "contents of",
    "content of",
    "what does",
    "what is in",
    "what's in",
    "full text",
)
_SUMMARIZE_WORDS = ("summarize", "summary", "tldr", "overview", "recap", "brief me", "in short", "high level")
_PARSE_WORDS = (
    "parse",
    "extract",
    "structure",
    "break down",
    "breakdown",
    "list requirements",
    "list claims",
    "pull out",
    "turn into",
)


class FileCatalogItem(BaseModel):
    locator: str
    kind: FileKind
    job_title: str
    candidate_name: str | None = None
    filename: str
    available: bool = True


class FileLocatorHit(BaseModel):
    locator: str
    reason: str = ""


class FileLocatorOutput(BaseModel):
    agent: str = "file_locator"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    action: FileAction = FileAction.locate
    want_download: bool = False
    summary: str = ""
    locators: list[str] = Field(default_factory=list)
    hits: list[FileLocatorHit] = Field(default_factory=list)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"['’]s\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" { ' '.join(text.split()) } "


def _kinds_from_query(query: str) -> set[FileKind]:
    padded = f" {query} "
    found: set[FileKind] = set()
    for kind, phrases in _KIND_PHRASES.items():
        if any(phrase in padded for phrase in phrases):
            found.add(kind)
    if re.search(r"\bjd\b", query):
        found.add(FileKind.jd)
    if re.search(r"\bcv\b", query):
        found.add(FileKind.resume)
    if "report" in query and FileKind.evidence not in found and FileKind.interview_brief not in found:
        found.add(FileKind.evidence)
        found.add(FileKind.interview_brief)
        found.add(FileKind.screening_brief)
    return found


def _name_hit(query: str, name: str | None) -> int:
    if not name:
        return 0
    normalized_name = _normalize(name).strip()
    if not normalized_name:
        return 0
    if f" {normalized_name} " in query:
        return 8
    parts = [part for part in normalized_name.split() if len(part) >= 3]
    hits = sum(1 for part in parts if f" {part} " in query)
    if hits == len(parts) and parts:
        return 7
    if hits:
        return 4
    return 0


def _title_hit(query: str, title: str) -> int:
    normalized = _normalize(title).strip()
    if not normalized:
        return 0
    if f" {normalized} " in query:
        return 6
    parts = [part for part in normalized.split() if len(part) >= 4]
    hits = sum(1 for part in parts if f" {part} " in query)
    if hits >= 2:
        return 4
    if hits == 1:
        return 2
    return 0


def _wants_download(query: str) -> bool:
    return any(word in query for word in _DOWNLOAD_WORDS)


def detect_action(query: str) -> FileAction:
    normalized = _normalize(query)
    if any(word in normalized for word in _PARSE_WORDS):
        return FileAction.parse
    if any(word in normalized for word in _SUMMARIZE_WORDS):
        return FileAction.summarize
    if any(word in normalized for word in _READ_WORDS):
        return FileAction.read
    if _wants_download(normalized):
        return FileAction.download
    return FileAction.locate


def _resolve_action(query: str, action: FileAction | None, want_download: bool) -> FileAction:
    detected = detect_action(query)
    if action is not None and action != FileAction.locate:
        resolved = action
    else:
        resolved = detected
    if resolved == FileAction.locate and want_download:
        return FileAction.download
    if resolved in {FileAction.read, FileAction.summarize, FileAction.parse}:
        return resolved
    if want_download and resolved == FileAction.locate:
        return FileAction.download
    return resolved


def heuristic_locate(query: str, catalog: list[FileCatalogItem]) -> FileLocatorOutput:
    normalized = _normalize(query)
    kinds = _kinds_from_query(normalized)
    action = detect_action(query)
    want_download = action == FileAction.download
    scored: list[tuple[int, FileCatalogItem, str]] = []
    for item in catalog:
        score = 0
        reasons: list[str] = []
        if kinds:
            if item.kind in kinds:
                score += 6
                reasons.append(item.kind.value.replace("_", " "))
            else:
                continue
        name_score = _name_hit(normalized, item.candidate_name)
        if name_score:
            score += name_score
            reasons.append(item.candidate_name or "")
        title_score = _title_hit(normalized, item.job_title)
        if title_score:
            score += title_score
            reasons.append(item.job_title)
        filename = _normalize(item.filename).strip()
        if filename and f" {filename} " in normalized:
            score += 5
            reasons.append(item.filename)
        if not item.available:
            score -= 1
        if score > 0:
            scored.append((score, item, ", ".join(part for part in reasons if part)))
    scored.sort(key=lambda row: (-row[0], row[1].kind.value, row[1].filename))
    picked = scored[:8]
    locators = [item.locator for _, item, _ in picked]
    hits = [FileLocatorHit(locator=item.locator, reason=reason or "Matched the request") for _, item, reason in picked]
    if not picked:
        summary = "No matching file was found. Name the candidate, role, or file kind (JD, resume, transcript, match and gaps, interview brief, evidence report)."
    elif len(picked) == 1:
        item = picked[0][1]
        who = item.candidate_name or item.job_title
        summary = f"Found {item.kind.value.replace('_', ' ')} for {who}."
    else:
        summary = f"Found {len(picked)} matching files."
    return FileLocatorOutput(
        action=action,
        want_download=want_download,
        summary=summary,
        locators=locators,
        hits=hits,
    )


async def locate_files(
    query: str,
    catalog: list[FileCatalogItem],
    config: LLMConfig | None,
) -> FileLocatorOutput:
    fallback = heuristic_locate(query, catalog)
    by_locator = {item.locator: item for item in catalog}
    if not catalog:
        return FileLocatorOutput(
            summary="No files are stored yet. Upload a JD or resume first.",
            warnings=["empty_catalog"],
        )
    if config is None or not config.api_key:
        fallback.warnings.append("heuristic_only")
        return fallback
    compact = [
        {
            "locator": item.locator,
            "kind": item.kind.value,
            "job_title": item.job_title,
            "candidate_name": item.candidate_name,
            "filename": item.filename,
            "available": item.available,
        }
        for item in catalog
    ]
    try:
        result = await complete_json(
            config,
            system=SYSTEM,
            user=f"Recruiter request:\n{query}\n\nCatalog:\n{json.dumps(compact, indent=2)}",
            schema=FileLocatorOutput,
            agent="file_locator",
        )
    except LLMError:
        fallback.warnings.append("llm_unavailable")
        return fallback
    locators: list[str] = []
    for locator in result.locators:
        if locator in by_locator and locator not in locators:
            locators.append(locator)
    for hit in result.hits:
        if hit.locator in by_locator and hit.locator not in locators:
            locators.append(hit.locator)
    if not locators:
        return fallback
    reasons = {hit.locator: hit.reason for hit in result.hits if hit.locator in by_locator}
    result.locators = locators[:8]
    result.hits = [
        FileLocatorHit(locator=locator, reason=reasons.get(locator) or "Matched the request")
        for locator in result.locators
    ]
    if not result.summary:
        result.summary = fallback.summary
    result.action = _resolve_action(query, result.action, result.want_download)
    result.want_download = result.action == FileAction.download
    return result
