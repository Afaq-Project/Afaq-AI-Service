"""Integration tests for MatchCalculator evaluated against the 25 real scraped opportunities fixture."""

import json
from pathlib import Path
from typing import Any

import pytest

from src.modules.matching.models import (
    MATCH_SCORE_WEIGHTS,
    CategoryScoreDTO,
    MatchScoreResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.match_calculator import MatchCalculator


@pytest.fixture(scope="module")
def calculator() -> MatchCalculator:
    return MatchCalculator()


@pytest.fixture(scope="module")
def real_opportunities() -> list[dict[str, Any]]:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "real_cleaned_opportunities_25.json"
    )
    if fixture_path.exists():
        with open(fixture_path, encoding="utf-8") as f:
            return json.load(f)[:25]

    scratch_path = Path(
        r"C:\Users\msi\.gemini\antigravity\brain\399f96b8-3165-4f5f-8dd6-9f60fd12604a\scratch\audited_opps_clean.json"
    )
    if scratch_path.exists():
        with open(scratch_path, encoding="utf-8") as f:
            return json.load(f)[:25]

    raise FileNotFoundError("Could not find 25 real opportunities fixture dataset.")


@pytest.fixture
def sample_profiles() -> dict[str, UserProfileDTO]:
    return {
        "cs_strong": UserProfileDTO(
            user_id="u_cs_strong",
            first_name="Ahmed",
            nationality="Palestinian",
            education_level="bachelor",
            fields_of_study=[
                {"name": "Computer Science"},
                {"name": "Software Engineering"},
            ],
            skills=[
                {"name": "Python"},
                {"name": "Machine Learning"},
                {"name": "Docker"},
                {"name": "SQL"},
            ],
            educations=[
                {
                    "degree": "Bachelor of Science",
                    "major": "Computer Science",
                    "gpa_normalized_4": 3.85,
                }
            ],
            languages=[
                {"name": "Arabic", "proficiency": "native"},
                {"name": "English", "proficiency": "c1"},
            ],
            experience_level="3",
        ),
        "humanities_fresh": UserProfileDTO(
            user_id="u_humanities_fresh",
            first_name="Layla",
            nationality="Palestinian",
            education_level="bachelor",
            fields_of_study=[{"name": "English Literature"}],
            skills=[{"name": "Creative Writing"}, {"name": "Public Speaking"}],
            educations=[
                {
                    "degree": "Bachelor of Arts",
                    "major": "English Literature",
                    "gpa_normalized_4": 3.2,
                }
            ],
            languages=[
                {"name": "Arabic", "proficiency": "native"},
                {"name": "English", "proficiency": "b2"},
            ],
            experience_level=None,
        ),
        "empty_profile": UserProfileDTO(
            user_id="u_empty",
            nationality="Jordanian",
            education_level=None,
            fields_of_study=[],
            skills=[],
            educations=[],
            languages=[],
            experience_level=None,
        ),
    }


# ============================================================================
# 1. Real Data Scoring Contract & Invariant Validation
# ============================================================================


def test_real_opportunities_scoring_contract_invariants(
    calculator: MatchCalculator,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies that scoring all 25 real opportunities across diverse candidate profiles obeys all invariants."""
    assert len(real_opportunities) == 25

    expected_categories = {"field_of_study", "skills", "gpa", "language", "experience"}

    for profile_name, user_profile in sample_profiles.items():
        for i, opp in enumerate(real_opportunities):
            res = calculator.calculate_match_score(user_profile, opp)

            # Invariant 1: Result Type
            assert isinstance(
                res, MatchScoreResultDTO
            ), f"Failed for profile={profile_name}, opp={i}"

            # Invariant 2: Score Bounds
            assert (
                0 <= res.score_pct <= 100
            ), f"score_pct out of bounds: {res.score_pct}"
            assert (
                0.0 <= res.raw_score <= 100.0
            ), f"raw_score out of bounds: {res.raw_score}"
            assert (
                0.0 <= res.coverage_pct <= 100.0
            ), f"coverage_pct out of bounds: {res.coverage_pct}"

            # Invariant 3: Calculation Version
            assert res.calculation_version == 1

            # Invariant 4: Categories Dict
            assert set(res.categories.keys()) == expected_categories
            assert (
                "age" not in res.categories
            )  # Age must NEVER be in scoring categories

            # Invariant 5: Category SRS Weights
            for cat_name, expected_weight in MATCH_SCORE_WEIGHTS.items():
                cat_dto = res.categories[cat_name]
                assert isinstance(cat_dto, CategoryScoreDTO)
                assert cat_dto.weight == expected_weight
                assert isinstance(cat_dto.reason, str) and len(cat_dto.reason) > 0


def test_real_opportunities_determinism(
    calculator: MatchCalculator,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies that running MatchCalculator twice on identical inputs produces bitwise identical results."""
    user = sample_profiles["cs_strong"]

    for opp in real_opportunities:
        res1 = calculator.calculate_match_score(user, opp)
        res2 = calculator.calculate_match_score(user, opp)

        assert res1.score_pct == res2.score_pct
        assert res1.raw_score == res2.raw_score
        assert res1.coverage_pct == res2.coverage_pct
        assert res1.applicable_categories == res2.applicable_categories
        assert res1.uncomputable_categories == res2.uncomputable_categories
        assert res1.missing_user_categories == res2.missing_user_categories
        assert res1.silent_opportunity_categories == res2.silent_opportunity_categories

        for cat_key in res1.categories:
            c1 = res1.categories[cat_key]
            c2 = res2.categories[cat_key]
            assert c1.score_pct == c2.score_pct
            assert c1.is_applicable == c2.is_applicable
            assert c1.is_computable == c2.is_computable
            assert c1.reason == c2.reason


def test_real_opportunities_batch_execution(
    calculator: MatchCalculator,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies batch execution across all 25 real opportunities."""
    user = sample_profiles["cs_strong"]
    results = calculator.calculate_match_scores(user, real_opportunities)

    assert len(results) == 25
    for res in results:
        assert isinstance(res, MatchScoreResultDTO)
        assert 0 <= res.score_pct <= 100
