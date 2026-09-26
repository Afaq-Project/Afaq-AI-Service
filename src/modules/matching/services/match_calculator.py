"""Match scoring engine implementing Dynamic Denominator and Safe V1 rules."""

from datetime import UTC, datetime
from typing import Any

from src.modules.matching.models import (
    MATCH_SCORE_WEIGHTS,
    CategoryScoreDTO,
    MatchScoreResultDTO,
    OpportunityRequirementsDTO,
    RequirementStatus,
)
from src.modules.matching.services.category_evaluators import (
    evaluate_experience,
    evaluate_field_of_study,
    evaluate_gpa,
    evaluate_language,
    evaluate_skills,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor
from src.modules.scraping.services.normalization_service import NormalizationService


def calculate_match_score(
    user_profile: Any,
    opportunity_or_requirements: Any,
    normalizer: NormalizationService | None = None,
    requirement_extractor: RequirementExtractor | None = None,
) -> MatchScoreResultDTO:
    """Convenience function calculating match score for a user and opportunity."""
    calculator = MatchCalculator(
        normalization_service=normalizer,
        requirement_extractor=requirement_extractor,
    )
    return calculator.calculate_match_score(user_profile, opportunity_or_requirements)


class MatchCalculator:
    """Afaq AI Matching Engine — Match Scoring Calculator.

    Calculates deterministic, explainable match scores across 5 fixed SRS categories:
    - Field of Study (30%)
    - Skills / Interests (25%)
    - GPA (20%)
    - Language (15%)
    - Experience (10%)

    Applies the approved Safe V1 rules and Dynamic Denominator normalization.
    """

    def __init__(
        self,
        normalization_service: NormalizationService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self.normalizer = normalization_service or NormalizationService()
        self.extractor = requirement_extractor or RequirementExtractor(
            normalization_service=self.normalizer
        )

    def calculate_match_score(
        self,
        user_profile: Any,
        opportunity_or_requirements: Any,
    ) -> MatchScoreResultDTO:
        """Calculates match score between user profile and opportunity requirements."""
        # 1. Resolve Opportunity Requirements
        if isinstance(opportunity_or_requirements, OpportunityRequirementsDTO):
            reqs = opportunity_or_requirements
        else:
            reqs = self.extractor.extract_requirements(opportunity_or_requirements)

        # 2. Evaluate 5 scoring categories independently
        categories: dict[str, CategoryScoreDTO] = {
            "field_of_study": evaluate_field_of_study(
                user_profile, reqs.field_of_study, normalizer=self.normalizer
            ),
            "skills": evaluate_skills(
                user_profile, reqs.skills, normalizer=self.normalizer
            ),
            "gpa": evaluate_gpa(user_profile, reqs.gpa, normalizer=self.normalizer),
            "language": evaluate_language(
                user_profile, reqs.language, normalizer=self.normalizer
            ),
            "experience": evaluate_experience(
                user_profile, reqs.experience, normalizer=self.normalizer
            ),
        }

        # 3. Classify metadata lists
        applicable_categories: list[str] = []
        uncomputable_categories: list[str] = []
        missing_user_categories: list[str] = []
        silent_opportunity_categories: list[str] = []

        for cat_name, cat_score in categories.items():
            if cat_score.is_applicable:
                applicable_categories.append(cat_name)

            if (
                not cat_score.is_computable
                and cat_score.extracted_requirement is not None
            ):
                uncomputable_categories.append(cat_name)

            if (
                cat_score.extracted_requirement is not None
                and cat_score.extracted_requirement.status == RequirementStatus.REQUIRED
                and cat_score.is_computable
                and cat_score.score_pct == 0.0
                and cat_score.user_data_used is None
            ):
                missing_user_categories.append(cat_name)

            if (
                cat_score.extracted_requirement is None
                or cat_score.status == RequirementStatus.UNKNOWN
                or cat_score.status == RequirementStatus.NOT_REQUIRED
            ):
                silent_opportunity_categories.append(cat_name)

        # 4. Dynamic Denominator Aggregation
        active_weight_sum = sum(
            categories[name].weight for name in applicable_categories
        )
        total_possible_weight = sum(MATCH_SCORE_WEIGHTS.values())

        if active_weight_sum > 0:
            coverage_pct = round((active_weight_sum / total_possible_weight) * 100.0, 2)
            sum_weighted_pct = sum(
                categories[name].weight * ((categories[name].score_pct or 0.0) / 100.0)
                for name in applicable_categories
            )
            raw_score = (sum_weighted_pct / active_weight_sum) * 100.0
            score_pct = int(round(raw_score))
            score_pct = max(0, min(100, score_pct))
            raw_score = round(raw_score, 2)
        else:
            coverage_pct = 0.0
            raw_score = 0.0
            score_pct = 0

        # Resolve user_id and opportunity_id
        user_id = (
            user_profile.get("user_id")
            if isinstance(user_profile, dict)
            else getattr(user_profile, "user_id", None)
        )
        opp_id = reqs.opportunity_id
        if opp_id is None:
            if isinstance(opportunity_or_requirements, dict):
                opp_id = opportunity_or_requirements.get(
                    "id"
                ) or opportunity_or_requirements.get("opportunity_id")
            else:
                opp_id = getattr(opportunity_or_requirements, "id", None) or getattr(
                    opportunity_or_requirements, "opportunity_id", None
                )

        return MatchScoreResultDTO(
            user_id=user_id,
            opportunity_id=opp_id,
            score_pct=score_pct,
            raw_score=raw_score,
            coverage_pct=coverage_pct,
            calculation_version=1,
            categories=categories,
            applicable_categories=applicable_categories,
            uncomputable_categories=uncomputable_categories,
            missing_user_categories=missing_user_categories,
            silent_opportunity_categories=silent_opportunity_categories,
            calculated_at=datetime.now(UTC),
        )

    def calculate_match_scores(
        self,
        user_profile: Any,
        opportunities: list[Any],
    ) -> list[MatchScoreResultDTO]:
        """Calculates match scores for a user profile across a list of opportunities."""
        return [self.calculate_match_score(user_profile, opp) for opp in opportunities]
