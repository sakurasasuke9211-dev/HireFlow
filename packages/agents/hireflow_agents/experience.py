"""Deterministic professional experience extraction and JD range checks."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_YEARS_IN_TEXT = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?(?:\s+(?:work|professional))?\s*(?:experience|exp)?",
    re.IGNORECASE,
)
_YEAR_RANGE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-–to]+\s*(\d+(?:\.\d+)?)\s*(?:\+?\s*)?years?",
    re.IGNORECASE,
)
_YEAR_MIN = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", re.IGNORECASE)
_DATE_RANGE = re.compile(
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\b\d{4})\s*"
    r"[-–—to]+\s*"
    r"(\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\b\d{4}|present|current|now)",
    re.IGNORECASE,
)
_MONTH = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_year_range(requirement_text: str) -> tuple[float | None, float | None]:
    lowered = requirement_text.lower()
    range_match = _YEAR_RANGE.search(lowered)
    if range_match:
        return float(range_match.group(1)), float(range_match.group(2))
    min_match = _YEAR_MIN.search(lowered)
    if min_match:
        return float(min_match.group(1)), None
    return None, None


def classify_experience_years(requirement_text: str, years: float) -> str:
    """Return matched | partial | missing for JD experience bands like 2-3 years."""
    min_years, max_years = parse_year_range(requirement_text)
    if min_years is None:
        return "missing"
    if years + 0.25 < min_years:
        return "missing"
    if max_years is not None and years > max_years + 0.25:
        return "partial"
    return "matched"


def years_meets_requirement(requirement_text: str, years: float) -> bool:
    """True when the candidate meets at least the minimum (includes overqualified)."""
    return classify_experience_years(requirement_text, years) in {"matched", "partial"}


def years_from_text(*sources: str) -> float | None:
    found: list[float] = []
    for source in sources:
        if not source:
            continue
        for match in _YEARS_IN_TEXT.finditer(source):
            found.append(float(match.group(1)))
    return max(found) if found else None


def _parse_date_token(token: str) -> datetime | None:
    cleaned = token.strip().lower()
    if cleaned in {"present", "current", "now"}:
        return datetime.now(UTC)
    month_match = re.match(r"([a-z]+)\.?\s+(\d{4})", cleaned)
    if month_match:
        month_key = month_match.group(1)[:4]
        month = _MONTH.get(month_key[:3]) or _MONTH.get(month_key[:4])
        if month:
            return datetime(int(month_match.group(2)), month, 1)
    year_match = re.match(r"(\d{4})", cleaned)
    if year_match:
        return datetime(int(year_match.group(1)), 1, 1)
    return None


def years_from_employment_dates(*sources: str) -> float | None:
    spans: list[float] = []
    now = datetime.now(UTC)
    for source in sources:
        if not source:
            continue
        for match in _DATE_RANGE.finditer(source):
            start = _parse_date_token(match.group(1))
            end = _parse_date_token(match.group(2))
            if start is None or end is None:
                continue
            months = max(0.0, (end.year - start.year) * 12 + (end.month - start.month))
            spans.append(round(months / 12, 1))
    return max(spans) if spans else None


def resolve_years_experience(
    *,
    summary: str | None = None,
    resume_text: str | None = None,
    claim_texts: list[str] | None = None,
    current: float | None = None,
) -> float | None:
    sources = [summary or "", resume_text or "", *(claim_texts or [])]
    candidates: list[float] = []
    if current is not None:
        try:
            candidates.append(float(current))
        except (TypeError, ValueError):
            pass
    text_years = years_from_text(*sources)
    if text_years is not None:
        candidates.append(text_years)
    date_years = years_from_employment_dates(*sources)
    if date_years is not None:
        candidates.append(date_years)
    return max(candidates) if candidates else None
