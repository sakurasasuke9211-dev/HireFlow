from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from hireflow_domain.enums import FileAction, FileKind

PROMPT_VERSION = "file_assistant.v1"

_FOLLOWUP_HINTS = (
    "that",
    "this",
    "it",
    "the same",
    "same one",
    "same file",
    "that one",
    "this one",
    "that file",
    "this file",
)
_SHORT_FOLLOWUP = re.compile(
    r"^(download|get|save|read|open|show|summarize|summary|parse|extract)(\s+it|\s+that|\s+this)?\.?$",
    re.I,
)


class FileAssistantChatContext(BaseModel):
    primary_locator: str | None = None
    candidate_name: str | None = None
    job_title: str | None = None
    kind: FileKind | None = None


class FileAssistantChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)
    context: FileAssistantChatContext | None = None


def _last_context(turns: list[FileAssistantChatTurn]) -> FileAssistantChatContext | None:
    for turn in reversed(turns[:-1]):
        if turn.context and (
            turn.context.primary_locator or turn.context.candidate_name or turn.context.kind
        ):
            return turn.context
    return None


def _kind_phrase(kind: FileKind) -> str:
    return {
        FileKind.jd: "job description",
        FileKind.resume: "resume",
        FileKind.transcript: "transcript",
        FileKind.screening_brief: "match and gaps",
        FileKind.interview_brief: "interview brief",
        FileKind.evidence: "evidence report",
    }[kind]


def resolve_query(turns: list[FileAssistantChatTurn]) -> str:
    if not turns:
        return ""
    latest = turns[-1].content.strip()
    if not latest:
        return latest
    ctx = _last_context(turns)
    if ctx is None:
        return latest
    lowered = latest.lower()
    needs_context = (
        any(hint in lowered for hint in _FOLLOWUP_HINTS)
        or bool(_SHORT_FOLLOWUP.match(latest.strip()))
        or len(latest.split()) <= 4
    )
    if not needs_context:
        return latest
    subject_parts: list[str] = []
    if ctx.candidate_name:
        subject_parts.append(f"{ctx.candidate_name}'s")
    if ctx.kind:
        subject_parts.append(_kind_phrase(ctx.kind))
    elif ctx.job_title:
        subject_parts.append(ctx.job_title)
    if not subject_parts:
        return latest
    return f"{latest} {' '.join(subject_parts)}"


def compose_reply(
    *,
    user_message: str,
    action: FileAction,
    summary: str,
    hits: list[dict],
    answer: str | None,
    want_download: bool,
) -> str:
    del user_message
    if answer:
        opener = {
            FileAction.read: "Here's what that file says:",
            FileAction.summarize: "Here's a summary:",
            FileAction.parse: "Here's the structured breakdown:",
        }.get(action, summary or "Here's what I found:")
        return f"{opener}\n\n{answer}".strip()

    if not hits:
        return (
            "I looked through your stored files but couldn't find a match. "
            "Try naming the candidate (for example Soumya), the role, or the kind of file — "
            "JD, resume, transcript, match and gaps, interview brief, or evidence report."
        )

    if want_download and len(hits) == 1 and hits[0].get("available"):
        hit = hits[0]
        return f"Done — I downloaded {hit.get('label', 'the file')} ({hit.get('filename', 'file')})."

    if len(hits) == 1:
        hit = hits[0]
        label = hit.get("label", "that file")
        if not hit.get("available"):
            return (
                f"I found {label}, but it isn't ready yet. "
                "Run screening or generate the report first, then ask me again."
            )
        return (
            f"I found {label}. You can download it below, "
            "or ask me to read, summarize, or parse it."
        )

    lines = [summary or f"I found {len(hits)} matching files:"]
    for index, hit in enumerate(hits[:5], start=1):
        suffix = "" if hit.get("available") else " (not ready yet)"
        lines.append(f"{index}. {hit.get('label', 'File')}{suffix}")
    if len(hits) > 5:
        lines.append(f"...and {len(hits) - 5} more.")
    lines.append("Tell me which one you want, or ask me to download, read, or summarize it.")
    return "\n".join(lines)


def context_from_hits(
    hits: list[dict],
    *,
    primary_locator: str | None,
) -> FileAssistantChatContext | None:
    if not hits and not primary_locator:
        return None
    hit = hits[0] if hits else None
    if primary_locator and hits:
        for item in hits:
            if item.get("locator") == primary_locator:
                hit = item
                break
    if hit is None:
        return FileAssistantChatContext(primary_locator=primary_locator)
    kind = hit.get("kind")
    return FileAssistantChatContext(
        primary_locator=primary_locator or hit.get("locator"),
        candidate_name=hit.get("candidate_name"),
        job_title=hit.get("job_title"),
        kind=FileKind(kind) if isinstance(kind, str) else kind,
    )
