from __future__ import annotations

import re

from pydantic import BaseModel, Field

from hireflow_agents.llm import LLMConfig, LLMError, complete_json
from hireflow_domain.enums import Speaker

PROMPT_VERSION = "transcript_parser.v1"
MAX_CHARS = 14000
_STOP = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "your",
    "you",
}
_SPEAKER_LINE = re.compile(
    r"^(?:\[?\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\]?\s*)?(?P<name>[A-Za-z][A-Za-z .'-]{0,48})\s*[:\-–]\s*(?P<body>.+)$"
)
_RECRUITER_NAMES = {
    "recruiter",
    "interviewer",
    "hiring manager",
    "hiringmanager",
    "hm",
    "panel",
    "moderator",
}
_CANDIDATE_NAMES = {"candidate", "interviewee", "applicant", "talent"}
_VTT_TS = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s+-->\s+")


class ParsedTurn(BaseModel):
    speaker: str = Speaker.unknown.value
    text: str
    char_start: int | None = None
    char_end: int | None = None
    requirement_id: str | None = None
    planned_question_id: str | None = None


class TranscriptParserOutput(BaseModel):
    agent: str = "transcript_parser"
    schema_version: str = "1.0"
    warnings: list[str] = Field(default_factory=list)
    turns: list[ParsedTurn] = Field(default_factory=list)


SYSTEM = """You are HireFlow's Transcript Parser. Segment an interview transcript into turns.

Rules:
- speaker is recruiter | candidate | unknown. Interviewer/hiring manager = recruiter. Interviewee = candidate.
- Keep each turn's text verbatim. Do not paraphrase.
- Map a turn to requirement_id / planned_question_id only when the topic clearly matches. Leave null otherwise.
- Do not drop off-plan discussion.
- Do not include UUIDs in the turn text.
- If speaker labels are missing, use unknown rather than guessing.
"""


def _tokens(text: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9+#.]+", text.lower()) if item not in _STOP and len(item) > 1}


def _coerce_speaker(raw: str, *, candidate_name: str | None) -> Speaker:
    name = re.sub(r"\s+", " ", (raw or "").strip().lower())
    compact = name.replace(" ", "")
    if name in _RECRUITER_NAMES or compact in _RECRUITER_NAMES:
        return Speaker.recruiter
    if name in _CANDIDATE_NAMES or compact in _CANDIDATE_NAMES:
        return Speaker.candidate
    candidate = (candidate_name or "").strip().lower()
    if candidate:
        parts = [part for part in candidate.split() if part]
        if name == candidate or compact == candidate.replace(" ", ""):
            return Speaker.candidate
        if parts and name == parts[0]:
            return Speaker.candidate
    return Speaker.unknown


def _vtt_lines(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.upper().startswith("WEBVTT") and "-->" not in stripped[:800]:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        upper = item.upper()
        if upper.startswith("WEBVTT") or upper.startswith("NOTE") or upper.startswith("STYLE"):
            continue
        if _VTT_TS.match(item) or item.isdigit():
            continue
        kept.append(item)
    return "\n".join(kept)


def _attach_spans(source: str, turns: list[ParsedTurn]) -> None:
    cursor = 0
    for turn in turns:
        needle = turn.text.strip()
        if not needle:
            continue
        idx = source.find(needle, cursor)
        if idx < 0:
            idx = source.find(needle)
        if idx >= 0:
            turn.char_start = idx
            turn.char_end = idx + len(needle)
            cursor = turn.char_end


def _map_turns(
    turns: list[ParsedTurn],
    *,
    requirements: list[dict],
    questions: list[dict],
) -> None:
    req_tokens = [(item.get("id"), item.get("label") or "", _tokens(str(item.get("label") or ""))) for item in requirements]
    q_tokens = [
        (item.get("id"), item.get("requirement_id"), _tokens(str(item.get("prompt") or "")), str(item.get("requirement_id") or ""))
        for item in questions
    ]
    for turn in turns:
        if turn.requirement_id:
            continue
        text = turn.text.lower()
        tokens = _tokens(turn.text)
        best_req = None
        best_score = 0.0
        for req_id, label, labels in req_tokens:
            if not req_id or not labels:
                continue
            overlap = len(tokens & labels) / max(len(labels), 1)
            if label.lower() and label.lower() in text:
                overlap = max(overlap, 0.8)
            if overlap > best_score:
                best_score = overlap
                best_req = req_id
        if best_req and best_score >= 0.45:
            turn.requirement_id = best_req
        if turn.planned_question_id:
            continue
        best_q = None
        best_q_score = 0.0
        for qid, req_id, labels, _req in q_tokens:
            if not qid or not labels:
                continue
            overlap = len(tokens & labels) / max(len(labels), 1)
            if overlap > best_q_score:
                best_q_score = overlap
                best_q = (qid, req_id)
        if best_q and best_q_score >= 0.35:
            turn.planned_question_id = best_q[0]
            if not turn.requirement_id:
                turn.requirement_id = best_q[1]


def fallback_parse(
    text: str,
    *,
    candidate_name: str | None = None,
    requirements: list[dict] | None = None,
    questions: list[dict] | None = None,
) -> TranscriptParserOutput:
    source = text or ""
    cleaned = _vtt_lines(source)
    warnings: list[str] = []
    turns: list[ParsedTurn] = []
    labeled = 0
    current_speaker = Speaker.unknown
    current: list[str] = []

    def flush() -> None:
        body = " ".join(part.strip() for part in current if part.strip()).strip()
        if body:
            turns.append(ParsedTurn(speaker=current_speaker.value, text=body))

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                flush()
                current = []
            continue
        matched = _SPEAKER_LINE.match(line)
        if matched:
            flush()
            current = []
            current_speaker = _coerce_speaker(matched.group("name"), candidate_name=candidate_name)
            if current_speaker != Speaker.unknown:
                labeled += 1
            current.append(matched.group("body").strip())
            continue
        if not current:
            current_speaker = Speaker.unknown
        current.append(line)
    flush()

    if not turns and cleaned.strip():
        chunks = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        turns = [ParsedTurn(speaker=Speaker.unknown.value, text=chunk) for chunk in chunks] or [
            ParsedTurn(speaker=Speaker.unknown.value, text=cleaned.strip())
        ]

    _attach_spans(source, turns)
    _map_turns(turns, requirements=requirements or [], questions=questions or [])

    if len(source.strip()) < 80:
        warnings.append("Transcript is too short to judge coverage.")
    if labeled == 0:
        warnings.append("Speaker labels are missing. Turns are marked unknown.")
    unknown = sum(1 for turn in turns if turn.speaker == Speaker.unknown.value)
    if turns and unknown / len(turns) >= 0.6:
        warnings.append("Most turns could not be attributed to recruiter or candidate.")
    unmapped = sum(1 for turn in turns if not turn.requirement_id)
    if turns and unmapped / len(turns) >= 0.75:
        warnings.append("Most turns could not be mapped to a requirement. Unmapped turns are still kept.")
    return TranscriptParserOutput(warnings=warnings, turns=turns)


def _normalize_output(
    parsed: TranscriptParserOutput,
    *,
    source: str,
    candidate_name: str | None,
    requirements: list[dict],
    questions: list[dict],
) -> TranscriptParserOutput:
    valid_req = {str(item.get("id")) for item in requirements if item.get("id")}
    valid_q = {str(item.get("id")) for item in questions if item.get("id")}
    q_req = {str(item.get("id")): str(item.get("requirement_id") or "") for item in questions}
    cleaned: list[ParsedTurn] = []
    for turn in parsed.turns:
        text = (turn.text or "").strip()
        if not text:
            continue
        speaker = _coerce_speaker(turn.speaker, candidate_name=candidate_name)
        if turn.speaker in {item.value for item in Speaker}:
            speaker = Speaker(turn.speaker)
        req_id = turn.requirement_id if turn.requirement_id in valid_req else None
        qid = turn.planned_question_id if turn.planned_question_id in valid_q else None
        if qid and not req_id:
            req_id = q_req.get(qid) or None
        cleaned.append(
            ParsedTurn(
                speaker=speaker.value,
                text=text,
                char_start=turn.char_start,
                char_end=turn.char_end,
                requirement_id=req_id,
                planned_question_id=qid,
            )
        )
    if not cleaned:
        return fallback_parse(source, candidate_name=candidate_name, requirements=requirements, questions=questions)
    _attach_spans(source, cleaned)
    _map_turns(cleaned, requirements=requirements, questions=questions)
    warnings = list(parsed.warnings)
    fallback = fallback_parse(source, candidate_name=candidate_name, requirements=requirements, questions=questions)
    for warning in fallback.warnings:
        if warning not in warnings:
            warnings.append(warning)
    return TranscriptParserOutput(warnings=warnings, turns=cleaned)


async def parse_transcript(
    text: str,
    config: LLMConfig,
    *,
    candidate_name: str | None = None,
    requirements: list[dict] | None = None,
    questions: list[dict] | None = None,
) -> TranscriptParserOutput:
    requirements = requirements or []
    questions = questions or []
    fallback = fallback_parse(text, candidate_name=candidate_name, requirements=requirements, questions=questions)
    snippet = text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n[truncated]"
    try:
        parsed = await complete_json(
            config,
            system=SYSTEM,
            user=(
                "Segment this interview transcript. Preserve wording.\n\n"
                f"Candidate name: {candidate_name or 'unknown'}\n"
                f"Requirements: {requirements}\n"
                f"Planned questions: {questions}\n\n"
                f"Transcript:\n{snippet}"
            ),
            schema=TranscriptParserOutput,
            agent="transcript_parser",
        )
    except LLMError:
        return fallback
    return _normalize_output(
        parsed,
        source=text,
        candidate_name=candidate_name,
        requirements=requirements,
        questions=questions,
    )
