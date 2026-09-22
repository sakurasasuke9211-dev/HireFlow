from __future__ import annotations

from collections.abc import Sequence

from hireflow_domain.enums import MatchStatus, OverallMatch, RequirementPriority

_STATUS_POINTS = {
    MatchStatus.MATCHED: 1.0,
    MatchStatus.PARTIALLY_MATCHED: 0.5,
    MatchStatus.UNCLEAR: 0.25,
    MatchStatus.MISSING: 0.0,
}

_PRIORITY_WEIGHT = {
    RequirementPriority.must_have: 3.0,
    RequirementPriority.unclear_priority: 2.0,
    RequirementPriority.nice_to_have: 1.0,
}


def score_overall_match(
    items: Sequence[tuple[MatchStatus, RequirementPriority]],
) -> OverallMatch | None:
    if not items:
        return None
    earned = 0.0
    total = 0.0
    must_earned = 0.0
    must_total = 0.0
    for status, priority in items:
        weight = _PRIORITY_WEIGHT[priority]
        points = _STATUS_POINTS[status]
        earned += weight * points
        total += weight
        if priority == RequirementPriority.must_have:
            must_earned += points
            must_total += 1.0
    ratio = earned / total if total else 0.0
    must_ratio = must_earned / must_total if must_total else ratio
    if all(status == MatchStatus.MATCHED for status, _ in items):
        return OverallMatch.perfect
    if ratio >= 0.85 and must_ratio >= 0.8:
        return OverallMatch.perfect
    if ratio >= 0.65 and must_ratio >= 0.5:
        return OverallMatch.good
    if ratio >= 0.35 or must_ratio >= 0.4:
        return OverallMatch.average
    return OverallMatch.poor
