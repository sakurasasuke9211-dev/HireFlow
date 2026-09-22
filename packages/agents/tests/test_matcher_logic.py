from hireflow_agents.experience import years_meets_requirement as _years_meets_requirement
from hireflow_agents.matcher import (
    apply_deterministic_overrides,
    resolve_requirement_status,
    status_from_flags,
    _education_satisfies,
)
from hireflow_domain.schemas import DimensionFlags
from hireflow_domain.enums import MatchStatus
from hireflow_domain.schemas import DimensionFlags


def test_education_mba_btech():
    assert _education_satisfies(
        "MBA or Bachelor's in Business/Engineering",
        ["MBA, IIM Indore", "B.Tech, Delhi Technological University"],
    )


def test_experience_range():
    assert _years_meets_requirement("Experience 2-3 years", 2.5)
    profile = {"years_experience": 2.5}
    claims = [
        {
            "id": "1",
            "kind": "years_claim",
            "skill_label": "Professional experience",
            "years": 2.5,
            "text": "2.5 years",
            "quote": "2+ years",
        }
    ]
    flags = apply_deterministic_overrides(
        DimensionFlags(),
        category="experience",
        requirement_text="Experience 2-3 years",
        profile=profile,
        claims=claims,
        supporting_ids=[],
    )
    assert status_from_flags(flags, category="experience") == MatchStatus.MATCHED


def test_four_years_is_partial_match_for_two_to_three_requirement():
    profile = {"years_experience": 4.0, "summary": "4 years of work experience"}
    flags = apply_deterministic_overrides(
        DimensionFlags(),
        category="experience",
        requirement_text="Experience 2-3 years",
        profile=profile,
        claims=[],
        supporting_ids=[],
    )
    assert (
        status_from_flags(
            flags,
            category="experience",
            requirement_text="Experience 2-3 years",
            profile=profile,
            experience_years=4.0,
        )
        == MatchStatus.PARTIALLY_MATCHED
    )


def test_experience_requirement_works_when_category_is_skill():
    profile = {"years_experience": 2.5, "summary": "2.5 years of experience"}
    status = resolve_requirement_status(
        requirement_text="Experience 2-3 years",
        normalized_label="Experience 2-3 years",
        category="skill",
        profile=profile,
        claims=[],
        flags=DimensionFlags(),
    )
    assert status == MatchStatus.MATCHED

    over_profile = {"years_experience": 3.5, "summary": "3.5+ years of experience"}
    over_status = resolve_requirement_status(
        requirement_text="Experience 2-3 years",
        normalized_label="Experience 2-3 years",
        category="skill",
        profile=over_profile,
        claims=[],
        flags=DimensionFlags(),
    )
    assert over_status == MatchStatus.PARTIALLY_MATCHED


def test_sql_matches_from_skills_list():
    profile = {"skills_listed": ["SQL", "Python", "Power BI"]}
    status = resolve_requirement_status(
        requirement_text="SQL",
        normalized_label="SQL",
        category="skill",
        profile=profile,
        claims=[],
        flags=DimensionFlags(),
    )
    assert status == MatchStatus.MATCHED


def test_mba_and_engineering_is_perfect_education_match():
    profile = {
        "education": [
            "MBA, Indian Institute of Management Indore",
            "B.Tech, Delhi Technological University",
        ]
    }
    assert (
        status_from_flags(
            DimensionFlags(),
            category="education",
            requirement_text="MBA or Bachelor's in Business/Engineering",
            profile=profile,
            claims=[],
        )
        == MatchStatus.MATCHED
    )


def test_stakeholder_maps_to_communication():
    claims = [
        {
            "id": "2",
            "kind": "project",
            "text": "Stakeholder management across teams",
            "quote": "Managed stakeholders",
        }
    ]
    flags = apply_deterministic_overrides(
        DimensionFlags(),
        category="soft_skill",
        requirement_text="Communication and interpersonal",
        profile={},
        claims=claims,
        supporting_ids=[],
    )
    assert status_from_flags(flags, category="soft_skill") == MatchStatus.MATCHED


def test_sales_funnel_maps_to_presales():
    claims = [
        {
            "id": "3",
            "kind": "project",
            "text": "Built sales funnel for internship",
            "quote": "sales funnel",
        }
    ]
    flags = apply_deterministic_overrides(
        DimensionFlags(),
        category="soft_skill",
        requirement_text="Presales familiarity",
        profile={},
        claims=claims,
        supporting_ids=[],
    )
    assert status_from_flags(flags, category="soft_skill") == MatchStatus.MATCHED
