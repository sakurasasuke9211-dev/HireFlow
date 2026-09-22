from hireflow_agents.experience import (
    classify_experience_years,
    resolve_years_experience,
    years_from_text,
    years_meets_requirement,
)


def test_four_years_is_partial_for_two_to_three_band():
    assert classify_experience_years("Experience 2-3 years", 4.0) == "partial"
    assert years_meets_requirement("Experience 2-3 years", 4.0)


def test_two_point_five_years_is_matched_for_two_to_three_band():
    assert classify_experience_years("Experience 2-3 years", 2.5) == "matched"


def test_years_from_summary():
    assert years_from_text("Business analyst with 4 years of work experience") == 4.0


def test_resolve_prefers_highest_signal():
    years = resolve_years_experience(
        summary="4 years of experience in analytics",
        resume_text="Indus Towers  Jan 2021 - Present",
        claim_texts=["Stakeholder management"],
        current=2.0,
    )
    assert years is not None and years >= 4.0
