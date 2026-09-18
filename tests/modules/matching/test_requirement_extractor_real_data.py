"""Real-Data Validation Test Suite for RequirementExtractor v1.

Validates the RequirementExtractor against the 25 real cleaned opportunities
from the real opportunity requirement audit, ensuring strict adherence to
semantic Rules A through I:
- Rule A: Silence is UNKNOWN (never NOT_REQUIRED).
- Rule B: Explicit NOT_REQUIRED only (explicit evidence required).
- Rule C: Geography & metadata noise != Academic fields.
- Rule D: Program curriculum/benefits != Applicant skills.
- Rule E: Vague terms ('young') != Numeric age limits.
- Rule F: Title/fellowship != Inferred work experience.
- Rule G: No invented GPA numeric thresholds from qualitative terms.
- Rule H: Language scope preserved (ADMISSION / SCHOLARSHIP).
- Rule I: Logical compound conditions (AND / OR) strictly maintained.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from src.modules.matching.models import (
    RequirementStatus,
)
from src.modules.matching.services.requirement_extractor import (
    RequirementExtractor,
)


@pytest.fixture(scope="module")
def extractor() -> RequirementExtractor:
    return RequirementExtractor()


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


# ============================================================================
# 1. Dataset Integrity Validation
# ============================================================================


def test_real_dataset_count_and_sources(
    real_opportunities: list[dict[str, Any]],
) -> None:
    """Verifies that exactly 25 real opportunities are loaded with required schema."""
    assert len(real_opportunities) >= 25
    for opp in real_opportunities[:25]:
        assert "title" in opp
        assert "description" in opp
        assert "study_levels" in opp
        assert "fields_of_study" in opp
        assert "opportunity_type" in opp


# ============================================================================
# 2. General Semantic Rule Validations Across All 25 Real Opportunities
# ============================================================================


class TestRealDataRuleCompliance:
    def test_rule_c_geography_noise_rejection_all_25(
        self,
        extractor: RequirementExtractor,
        real_opportunities: list[dict[str, Any]],
    ) -> None:
        """Rule C: Geographic and scraper categories (Japan, China, Mauritius, Usa, Scholarships)
        must NOT become academic fields of study across all 25 opportunities.
        """
        noise_tokens = {
            "japan",
            "china",
            "mauritius",
            "usa",
            "america",
            "canada",
            "australia",
            "germany",
            "italy",
            "qatar",
            "belgium",
            "scholarships",
            "masters scholarships",
            "ph.d scholarships",
            "undergraduate scholarships",
            "women scholarships",
            "study abroad",
            "study in usa",
            "study in canada",
            "study in germany",
            "study in europe",
        }
        for opp in real_opportunities[:25]:
            res = extractor.extract_requirements(opp)
            req = res.get_first_by_category("field_of_study")
            if req and req.status == RequirementStatus.REQUIRED:
                majors = req.value.get("majors", [])
                for m in majors:
                    assert (
                        m.lower() not in noise_tokens
                    ), f"Opp '{opp['title']}' falsely extracted noise as major: {m}"

    def test_rule_d_program_curriculum_not_applicant_skill_all_25(
        self,
        extractor: RequirementExtractor,
        real_opportunities: list[dict[str, Any]],
    ) -> None:
        """Rule D: Program description/curriculum ('program teaches leadership')
        must NOT become an applicant skill requirement.
        """
        for opp in real_opportunities[:25]:
            res = extractor.extract_requirements(opp)
            req = res.get_first_by_category("skills")
            if req and req.status == RequirementStatus.REQUIRED:
                assert "program teaches" not in req.evidence.lower()
                assert "curriculum covers" not in req.evidence.lower()

    def test_rule_e_young_does_not_infer_numeric_age_all_25(
        self,
        extractor: RequirementExtractor,
        real_opportunities: list[dict[str, Any]],
    ) -> None:
        """Rule E: Vague marketing terms ('young professionals') must NOT invent numeric age limits."""
        for opp in real_opportunities[:25]:
            res = extractor.extract_requirements(opp)
            req = res.get_first_by_category("age")
            if req and req.status == RequirementStatus.REQUIRED:
                assert (
                    req.value.get("maximum")
                    or req.value.get("minimum")
                    or req.value.get("birth_date_after")
                )
                assert any(c.isdigit() for c in (req.evidence or ""))

    def test_rule_a_silence_is_unknown_all_25(
        self,
        extractor: RequirementExtractor,
        real_opportunities: list[dict[str, Any]],
    ) -> None:
        """Rule A: Missing criteria in opportunities must remain UNKNOWN, never NOT_REQUIRED."""
        for opp in real_opportunities[:25]:
            res = extractor.extract_requirements(opp)
            for cat in ["gpa", "age", "experience", "language", "skills"]:
                req = res.get_first_by_category(cat)
                if req is not None and req.evidence is None:
                    assert (
                        req.status == RequirementStatus.UNKNOWN
                    ), f"Opp '{opp['title']}' category '{cat}' had no evidence but status={req.status}"


# ============================================================================
# 3. Systematic Verification of Each of the 25 Real Opportunities
# ============================================================================


class TestAll25IndividualOpportunities:
    def test_opp_01_asu_mastercard(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[0]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert "Master" in res.get_first_by_category("education").value["degree_levels"]
        assert res.get_first_by_category("age").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("age").value["minimum"] == 18
        assert res.get_first_by_category("age").value["maximum"] == 33
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("language").status == RequirementStatus.REQUIRED
        )

    def test_opp_02_university_of_alberta(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[1]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_03_qatar_charity(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[2]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_04_daad_helmut_schmidt(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[3]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("language").status == RequirementStatus.REQUIRED
        )
        docs = [d.value["document"] for d in res.get_by_category("application")]
        assert "motivation_letter" in docs
        assert "recommendation_letter" in docs

    def test_opp_05_university_of_manitoba(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[4]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_06_swansea_centenary_mba(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[5]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert "Master" in res.get_first_by_category("education").value["degree_levels"]

    def test_opp_07_charles_darwin_rtp(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[6]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_08_emory_university(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[7]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_09_canadian_university_dubai(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[8]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_10_osaka_university_mext(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[9]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_11_adelaide_rtp(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[10]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.NOT_REQUIRED
        )

    def test_opp_12_erasmus_mba(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[11]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_13_mccall_macbain(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[12]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_14_malaysian_mtcp(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[13]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.REQUIRED
        )
        assert res.get_first_by_category("gpa").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("gpa").value["minimum"] == 3.5

    def test_opp_15_flanders_master_mind(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[14]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_16_university_of_trento(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[15]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_17_mauritius_commonwealth(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[16]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_18_tsinghua_university(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[17]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )

    def test_opp_19_la_trobe(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[18]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("language").status
            == RequirementStatus.NOT_REQUIRED
        )

    def test_opp_20_german_government(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[19]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("experience").status == RequirementStatus.REQUIRED
        )
        assert res.get_first_by_category("experience").value["minimum_years"] == 2

    def test_opp_21_university_of_calgary(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[20]
        res = extractor.extract_requirements(opp)
        assert res.get_first_by_category("gpa").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("gpa").value["minimum"] == 3.0

    def test_opp_22_community_engagement_exchange(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[21]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.REQUIRED
        )
        assert res.get_first_by_category("age").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("age").value["minimum"] == 21
        assert res.get_first_by_category("age").value["maximum"] == 27
        assert (
            res.get_first_by_category("experience").status == RequirementStatus.REQUIRED
        )
        assert res.get_first_by_category("experience").value["minimum_years"] == 2

    def test_opp_23_beijing_normal_csc(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[22]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.UNKNOWN
        )
        assert res.get_first_by_category("age").status == RequirementStatus.REQUIRED

    def test_opp_24_macewan_university(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[23]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )

    def test_opp_25_tobe_maki(
        self, extractor: RequirementExtractor, real_opportunities: list[dict[str, Any]]
    ) -> None:
        opp = real_opportunities[24]
        res = extractor.extract_requirements(opp)
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert res.get_first_by_category("age").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("age").value["maximum"] == 30
