"""Match scoring engine implementing Two-Layer Option D Normalization for Afaq Matching Engine.

Nominal Category Weights:
- Field of Study: 30%
- Opportunity Requirements Match (ORM): 25%
- GPA / Academic Standing: 20%
- Language Proficiency: 15%
- Experience: 10%
Total = 100%

Scoring Semantics:
- Requirement Consolidation by (req_type, sub_key)
- GPA Model C: 70 + 30 * clamp((user - required) / (preferred - required), 0, 1)
- Language Model C for same test: 70 + 30 * clamp(...)
- Field of Study: Exact normalized string equality only
- Experience: Conservative area matching using _user_has_matching_experience_area
- Two-Layer Normalization (Option D):
  Layer 1 (Scholarship Applicability): Category genuinely absent from scholarship -> is_applicable = False,
  weight redistributed proportionally.
  Layer 2 (User Profile Completeness): Category required by scholarship but user data missing -> category
  remains is_applicable = True, weight REMAINS in global denominator (no redistribution).
- requirements_coverage_pct: metadata ONLY, sum of scholarship-applicable nominal weights.
"""

from datetime import UTC, datetime
from typing import Any

from src.modules.matching.models import (
    MATCH_SCORE_WEIGHTS,
    CategoryScoreDTO,
    MatchScoreResultDTO,
    OpportunityRequirementsDTO,
    RequirementStatus,
    RequirementType,
    UserProfileDTO,
)
from src.modules.matching.services.hard_filter_service import (
    _user_has_matching_experience_area,
)
from src.modules.matching.services.opportunity_requirements_matcher import (
    OpportunityRequirementsMatcher,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor
from src.modules.scraping.services.normalization_service import NormalizationService


def clamp(val: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamps a float value between min_val and max_val."""
    return max(min_val, min(val, max_val))


def evaluate_field_of_study(
    user_profile: UserProfileDTO,
    reqs: OpportunityRequirementsDTO,
    normalizer: NormalizationService,
) -> CategoryScoreDTO:
    """Evaluates Field of Study (30% weight) using exact normalized string equality ONLY."""
    category = "field_of_study"
    weight = MATCH_SCORE_WEIGHTS[category]

    fos_reqs = reqs.by_type(RequirementType.FIELD_OF_STUDY)
    if not fos_reqs:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=None,
            is_applicable=False,
            reason="Scholarship text contains no field of study restrictions (category not applicable at scholarship level)",
        )

    # Check for open to all
    for r in fos_reqs:
        if r.status == RequirementStatus.NOT_REQUIRED or r.value == "open_to_all":
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason="Scholarship explicitly open to all fields of study",
            )

    # Extract required and preferred field strings
    user_disciplines = [
        f.name.lower() for f in user_profile.fields_of_study if f.name
    ] + [e.major.lower() for e in user_profile.educations if e.major]

    if not user_disciplines:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=0.0,
            is_applicable=True,
            reason="Scholarship requires specific field of study, but user fields of study / majors are missing from profile",
        )

    all_req_fields: list[str] = []
    for r in fos_reqs:
        if isinstance(r.value, list):
            all_req_fields.extend([str(x).lower() for x in r.value])
        elif r.value:
            all_req_fields.append(str(r.value).lower())

    for udisc in user_disciplines:
        for rf in all_req_fields:
            if rf == udisc:
                return CategoryScoreDTO(
                    category=category,
                    weight=weight,
                    score=100.0,
                    is_applicable=True,
                    reason=f"User field/major '{udisc}' exactly matches required field '{rf}'",
                )

    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score=0.0,
        is_applicable=True,
        reason=f"User fields {user_disciplines[:3]} do not match required fields {all_req_fields[:3]}",
    )


def evaluate_gpa(
    user_profile: UserProfileDTO,
    reqs: OpportunityRequirementsDTO,
    normalizer: NormalizationService,
) -> CategoryScoreDTO:
    """Evaluates GPA (20% weight) using consolidated Model C continuous progression ratio.

    Model C Formula:
    70.0 + 30.0 * clamp((user_gpa - req_gpa) / (pref_gpa - req_gpa), 0.0, 1.0)
    """
    category = "gpa"
    weight = MATCH_SCORE_WEIGHTS[category]

    gpa_reqs = reqs.by_type(RequirementType.GPA)
    if not gpa_reqs:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=None,
            is_applicable=False,
            reason="Scholarship text contains no GPA requirements (category not applicable at scholarship level)",
        )

    # Check for explicitly not required
    if any(r.status == RequirementStatus.NOT_REQUIRED for r in gpa_reqs):
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=100.0,
            is_applicable=True,
            reason="Scholarship explicitly has no GPA restrictions",
        )

    # Extract required and preferred thresholds
    req_threshold: float | None = None
    pref_threshold: float | None = None

    for r in gpa_reqs:
        val = r.value
        if isinstance(val, dict):
            min_gpa = val.get("min_gpa_normalized_4")
            if min_gpa is not None:
                if r.status == RequirementStatus.REQUIRED:
                    if req_threshold is None or min_gpa > req_threshold:
                        req_threshold = min_gpa
                elif r.status == RequirementStatus.PREFERRED:
                    if pref_threshold is None or min_gpa > pref_threshold:
                        pref_threshold = min_gpa

    user_gpas = [
        edu.gpa_normalized_4
        for edu in user_profile.educations
        if edu.gpa_normalized_4 is not None
    ]

    if not user_gpas:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=0.0,
            is_applicable=True,
            reason="Scholarship requires specific GPA, but user GPA is missing from profile",
        )

    user_highest = max(user_gpas)

    if req_threshold is not None:
        if user_highest < req_threshold:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=0.0,
                is_applicable=True,
                reason=f"User GPA ({user_highest:.2f}) is below required baseline GPA ({req_threshold:.2f})",
            )

        # User passes baseline
        if pref_threshold is None or pref_threshold <= req_threshold:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason=f"User GPA ({user_highest:.2f}) meets required baseline GPA ({req_threshold:.2f})",
            )

        # Model C continuous progression ratio
        bonus_ratio = clamp(
            (user_highest - req_threshold) / (pref_threshold - req_threshold),
            0.0,
            1.0,
        )
        score = 70.0 + (30.0 * bonus_ratio)
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=round(score, 2),
            is_applicable=True,
            reason=(
                f"User GPA ({user_highest:.2f}) meets baseline GPA ({req_threshold:.2f}) "
                f"and scores {score:.1f}% towards preferred target ({pref_threshold:.2f})"
            ),
        )

    if pref_threshold is not None:
        # Only preferred threshold exists
        if user_highest >= pref_threshold:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason=f"User GPA ({user_highest:.2f}) meets preferred GPA target ({pref_threshold:.2f})",
            )
        bonus_ratio = clamp(user_highest / pref_threshold, 0.0, 1.0)
        score = 70.0 * bonus_ratio
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=round(score, 2),
            is_applicable=True,
            reason=f"User GPA ({user_highest:.2f}) scores {score:.1f}% towards preferred GPA target ({pref_threshold:.2f})",
        )

    # Qualitative or uncomputable
    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score=0.0,
        is_applicable=True,
        reason="GPA requirement uncomputable numerically",
    )


def evaluate_language(
    user_profile: UserProfileDTO,
    reqs: OpportunityRequirementsDTO,
    normalizer: NormalizationService,
) -> CategoryScoreDTO:
    """Evaluates Language Proficiency (15% weight) using consolidated Model C for same test."""
    category = "language"
    weight = MATCH_SCORE_WEIGHTS[category]

    lang_reqs = reqs.by_type(RequirementType.LANGUAGE)
    if not lang_reqs:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=None,
            is_applicable=False,
            reason="Scholarship text contains no language requirements (category not applicable at scholarship level)",
        )

    for r in lang_reqs:
        if (
            r.status == RequirementStatus.NOT_REQUIRED
            or r.value == "no_certificate_required"
        ):
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason="Scholarship explicitly has no language certificate restrictions",
            )

    # Collect test requirements by test_name
    req_tests: dict[str, float] = {}
    pref_tests: dict[str, float] = {}

    for r in lang_reqs:
        val = r.value
        if isinstance(val, dict):
            tests = val.get("tests", [])
            for t in tests:
                t_name = str(t.get("test") or "").upper()
                min_s = t.get("min_score")
                if t_name and min_s is not None:
                    if r.status == RequirementStatus.REQUIRED:
                        req_tests[t_name] = max(
                            req_tests.get(t_name, 0.0), float(min_s)
                        )
                    elif r.status == RequirementStatus.PREFERRED:
                        pref_tests[t_name] = max(
                            pref_tests.get(t_name, 0.0), float(min_s)
                        )

    if not req_tests and not pref_tests:
        # General proficiency requirement
        user_langs = [lang.name.lower() for lang in user_profile.languages if lang.name]
        if user_langs or user_profile.test_results:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason="User profile includes language proficiency",
            )
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=0.0,
            is_applicable=True,
            reason="Scholarship requires language proficiency, but user language data is missing from profile",
        )

    # Evaluate standardized test scores
    user_test_scores: dict[str, float] = {}
    for tr in user_profile.test_results:
        if tr.test_name and tr.score is not None:
            t_upper = tr.test_name.upper()
            user_test_scores[t_upper] = max(
                user_test_scores.get(t_upper, 0.0), float(tr.score)
            )

    if not user_test_scores:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=0.0,
            is_applicable=True,
            reason="Scholarship requires standardized language test, but user test results are missing from profile",
        )

    # Check required tests first
    for t_name, req_score in req_tests.items():
        if t_name in user_test_scores:
            u_score = user_test_scores[t_name]
            if u_score < req_score:
                return CategoryScoreDTO(
                    category=category,
                    weight=weight,
                    score=0.0,
                    is_applicable=True,
                    reason=f"User {t_name} score ({u_score}) is below required minimum ({req_score})",
                )
            # Passes required
            pref_score = pref_tests.get(t_name)
            if pref_score is None or pref_score <= req_score:
                return CategoryScoreDTO(
                    category=category,
                    weight=weight,
                    score=100.0,
                    is_applicable=True,
                    reason=f"User {t_name} score ({u_score}) meets required minimum ({req_score})",
                )

            bonus_ratio = clamp(
                (u_score - req_score) / (pref_score - req_score), 0.0, 1.0
            )
            score = 70.0 + (30.0 * bonus_ratio)
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=round(score, 2),
                is_applicable=True,
                reason=f"User {t_name} score ({u_score}) meets baseline ({req_score}) and scores {score:.1f}% towards preferred target ({pref_score})",
            )

    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score=0.0,
        is_applicable=True,
        reason=f"User test results {list(user_test_scores.keys())} do not match required test {list(req_tests.keys())}",
    )


def evaluate_experience(
    user_profile: UserProfileDTO,
    reqs: OpportunityRequirementsDTO,
    normalizer: NormalizationService,
) -> CategoryScoreDTO:
    """Evaluates Work/Research Experience (10% weight) using conservative area matching."""
    category = "experience"
    weight = MATCH_SCORE_WEIGHTS[category]

    exp_reqs = reqs.by_type(RequirementType.EXPERIENCE)
    if not exp_reqs:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=None,
            is_applicable=False,
            reason="Scholarship text contains no experience requirements (category not applicable at scholarship level)",
        )

    for r in exp_reqs:
        if (
            r.status == RequirementStatus.NOT_REQUIRED
            or r.value == "no_experience_required"
        ):
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason="Scholarship explicitly has no experience restrictions",
            )

    if not user_profile.experiences:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score=0.0,
            is_applicable=True,
            reason="Scholarship requires experience, but user experiences list is empty/missing from profile",
        )

    for r in exp_reqs:
        val = r.value
        req_area = "relevant_experience"
        if isinstance(val, dict):
            req_area = str(val.get("area") or "relevant_experience")
        elif isinstance(val, str):
            req_area = val

        if _user_has_matching_experience_area(user_profile, req_area):
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score=100.0,
                is_applicable=True,
                reason=f"User experiences match required experience area '{req_area}'",
            )

    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score=0.0,
        is_applicable=True,
        reason=f"User experiences {user_profile.experiences[:3]} do not match required experience area",
    )


class MatchCalculator:
    """Afaq AI Matching Engine – Final Score Aggregation Engine.

    Calculates deterministic, explainable match scores across 5 fixed SRS categories:
    - Field of Study (30%)
    - Opportunity Requirements Match (25%)
    - GPA / Academic Standing (20%)
    - Language Proficiency (15%)
    - Work/Research Experience (10%)

    Aggregation Method: Two-Layer Option D Normalization.
    - Layer 1 (Scholarship Applicability): Categories absent from scholarship text -> is_applicable = False,
      weight redistributed proportionally across active categories.
    - Layer 2 (User Profile Completeness): Categories required by scholarship but user profile data missing ->
      category remains is_applicable = True, neutral score = 0.0, weight REMAINS in global denominator.
    - requirements_coverage_pct: metadata ONLY (sum of active nominal weights / 100.0 * 100.0).
    """

    def __init__(
        self,
        normalization_service: NormalizationService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
        orm_matcher: OpportunityRequirementsMatcher | None = None,
    ) -> None:
        self._norm = normalization_service or NormalizationService()
        self._extractor = requirement_extractor or RequirementExtractor(self._norm)
        self._orm_matcher = orm_matcher or OpportunityRequirementsMatcher(
            self._norm, self._extractor
        )

    def calculate_match_score(
        self,
        user_profile: UserProfileDTO,
        opportunity_or_requirements: dict[str, Any] | OpportunityRequirementsDTO,
    ) -> MatchScoreResultDTO:
        """Calculates full match score result for a user profile and opportunity."""
        if isinstance(opportunity_or_requirements, OpportunityRequirementsDTO):
            reqs = opportunity_or_requirements
        else:
            reqs = self._extractor.extract(opportunity_or_requirements)

        opp_id = reqs.opportunity_id
        user_id = str(user_profile.user_id) if user_profile.user_id else None

        # Evaluate standalone categories
        fos_score = evaluate_field_of_study(user_profile, reqs, self._norm)
        gpa_score = evaluate_gpa(user_profile, reqs, self._norm)
        lang_score = evaluate_language(user_profile, reqs, self._norm)
        exp_score = evaluate_experience(user_profile, reqs, self._norm)
        orm_score = self._orm_matcher.to_category_score_dto(user_profile, reqs)

        category_scores = [fos_score, orm_score, gpa_score, lang_score, exp_score]

        # Layer 1: Filter to scholarship-applicable categories (is_applicable == True)
        scholarship_active = [cat for cat in category_scores if cat.is_applicable]

        if not scholarship_active:
            # Fallback: if all categories are non-applicable, default to 100.0
            total_score = 100.0
            requirements_coverage_pct = 0.0
        else:
            active_weight_sum = sum(cat.weight for cat in scholarship_active)
            requirements_coverage_pct = (active_weight_sum / 100.0) * 100.0

            # Option D Aggregation:
            # Sum(score * weight) / Sum(weight) for scholarship-applicable categories
            # Missing user data categories have is_applicable = True and score = 0.0
            score_numerator = sum(
                (cat.score or 0.0) * cat.weight for cat in scholarship_active
            )
            total_score = score_numerator / active_weight_sum

        is_preliminary = user_profile.is_matchable is not True

        return MatchScoreResultDTO(
            user_id=user_id,
            opportunity_id=opp_id,
            total_score=round(total_score, 2),
            requirements_coverage_pct=round(requirements_coverage_pct, 2),
            category_scores=category_scores,
            calculated_at=datetime.now(UTC).isoformat(),
            is_preliminary=is_preliminary,
        )

    def calculate_match_scores(
        self,
        user_profile: UserProfileDTO,
        opportunities: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], MatchScoreResultDTO]]:
        """Calculates match scores for a user profile across a list of opportunities."""
        return [
            (opp, self.calculate_match_score(user_profile, opp))
            for opp in opportunities
        ]
