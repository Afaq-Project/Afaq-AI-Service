"""Hard eligibility filter for Afaq AI Matching Engine.

Evaluates ALL REQUIRED requirements (nationality, education, GPA, age, language,
experience, financial need, field of study) as gating eligibility filters.

Rules:
- REQUIRED condition fails -> decision = INELIGIBLE (is_eligible = False).
- REQUIRED condition passes -> decision = ELIGIBLE (is_eligible = True).
- Missing user data, uncomputable, or low confidence -> decision = UNKNOWN (is_eligible = True, NOT excluded).
- PREFERRED, NOT_REQUIRED, UNKNOWN requirements -> ignored during hard filtering.
"""

from datetime import date
from typing import Any

from src.modules.matching.models import (
    OPEN_TO_ALL_NATIONALITIES,
    ConfidenceLevel,
    CriterionEvaluation,
    EligibilityDecision,
    ExtractedRequirement,
    HardFilterResultDTO,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementStatus,
    RequirementType,
    UserProfileDTO,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor
from src.modules.scraping.services.normalization_service import NormalizationService

# Study-level hierarchy for education level comparison
_LEVEL_ORDER = ["High School", "Diploma", "Bachelor", "Master", "PhD", "Postdoc"]
_LEVEL_RANK: dict[str, int] = {lvl: i for i, lvl in enumerate(_LEVEL_ORDER)}

import re  # noqa: E402


def _user_has_matching_experience_area(
    user_profile: UserProfileDTO,
    req_area: str,
) -> bool:
    """Checks if user_profile.experiences contains a matching experience area without naive substring search."""
    if not user_profile.experiences:
        return False

    req_area_clean = req_area.lower().strip()
    if req_area_clean in ("relevant_experience", "preferred", "no_experience_required"):
        return True  # Any non-empty experience entry matches generic requirement

    area_patterns = {
        "research": re.compile(r"(?i)\bresearch(?:er|ing|es|ed|ch)?\b"),
        "volunteering": re.compile(r"(?i)\bvolunteer(?:ing|s|ed)?\b"),
        "volunteer": re.compile(r"(?i)\bvolunteer(?:ing|s|ed)?\b"),
        "teaching": re.compile(r"(?i)\bteach(?:ing|er|es)?\b|\btutor(?:ing|s)?\b"),
        "clinical": re.compile(r"(?i)\bclinical|medical\b"),
        "leadership": re.compile(r"(?i)\bleader(?:ship|s)?\b"),
        "work": re.compile(
            r"(?i)\bwork(?:ing|ed)?\b|\bprofessional\b|\bemployment\b|\bjob\b"
        ),
    }

    pat = area_patterns.get(
        req_area_clean,
        re.compile(rf"(?i)\b{re.escape(req_area_clean)}\b"),
    )

    for exp_entry in user_profile.experiences:
        if pat.search(exp_entry):
            return True
    return False


def passes_nationality_filter(
    user_nationality: str | None,
    eligible_nationalities: list[str] | str | None,
    normalizer: NormalizationService,
) -> bool:
    """Legacy convenience function: returns True if user passes nationality constraint."""
    if not eligible_nationalities:
        return True
    if isinstance(eligible_nationalities, str):
        eligible_nationalities = [eligible_nationalities]
    if not user_nationality:
        return True  # Missing user data -> not excluded
    norm_user = (
        normalizer.normalize_country(user_nationality)
        or user_nationality.strip().lower()
    )
    for nat in eligible_nationalities:
        norm_nat = nat.strip().lower()
        if norm_nat in OPEN_TO_ALL_NATIONALITIES:
            return True
        if norm_user.lower() == norm_nat:
            return True
    return False


def passes_education_filter(
    user_education_level: str | None,
    required_study_levels: list[str],
    normalizer: NormalizationService,
) -> bool:
    """Legacy convenience function: returns True if user meets education level constraint."""
    if not required_study_levels:
        return True
    if not user_education_level:
        return True  # Missing user data -> not excluded
    normalized_levels = normalizer.normalize_study_levels(required_study_levels)
    user_rank = _LEVEL_RANK.get(user_education_level, -1)
    for required_level in normalized_levels:
        req_rank = _LEVEL_RANK.get(required_level, -1)
        if user_rank >= req_rank - 1 >= 0:
            return True
    return False


class HardFilterService:
    """Service evaluating all REQUIRED criteria as binary hard eligibility gates.

    Enforces the semantic contract:
    - REQUIRED = mandatory eligibility requirement.
    - Fails REQUIRED criteria -> INELIGIBLE (is_eligible = False).
    - Passes REQUIRED criteria -> ELIGIBLE.
    - Missing user data / uncomputable -> UNKNOWN (is_eligible = True, NOT excluded).
    """

    def __init__(
        self,
        normalization_service: NormalizationService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self._norm = normalization_service or NormalizationService()
        self._extractor = requirement_extractor or RequirementExtractor(self._norm)

    def evaluate_detailed(
        self,
        user_profile: UserProfileDTO,
        opportunity_or_requirements: dict[str, Any] | OpportunityRequirementsDTO,
    ) -> HardFilterResultDTO:
        """Evaluates all REQUIRED criteria for a user.

        Produces an explainable HardFilterResultDTO.
        Missing user data or uncomputable requirements result in UNKNOWN,
        which does NOT cause hard exclusion (is_eligible = True).
        """
        if isinstance(opportunity_or_requirements, OpportunityRequirementsDTO):
            reqs = opportunity_or_requirements
        else:
            reqs = self._extractor.extract(opportunity_or_requirements)

        criteria: list[CriterionEvaluation] = []
        failure_reasons: list[str] = []
        unknown_reasons: list[str] = []

        # Evaluate every extracted requirement with REQUIRED status
        for req in reqs.requirements:
            if req.status != RequirementStatus.REQUIRED:
                continue  # PREFERRED, NOT_REQUIRED, UNKNOWN are soft or neutral

            ev = self._evaluate_single_required_criterion(user_profile, req)
            criteria.append(ev)

            if ev.decision == EligibilityDecision.INELIGIBLE:
                failure_reasons.append(ev.reason)
            elif ev.decision == EligibilityDecision.UNKNOWN:
                unknown_reasons.append(ev.reason)

        if failure_reasons:
            decision = EligibilityDecision.INELIGIBLE
            is_eligible = False
        elif unknown_reasons and not any(
            ev.decision == EligibilityDecision.ELIGIBLE for ev in criteria
        ):
            decision = EligibilityDecision.UNKNOWN
            is_eligible = True
        else:
            decision = EligibilityDecision.ELIGIBLE
            is_eligible = True

        return HardFilterResultDTO(
            is_eligible=is_eligible,
            decision=decision,
            criteria=criteria,
            failure_reasons=failure_reasons,
            unknown_reasons=unknown_reasons,
        )

    def evaluate(
        self,
        user_profile: UserProfileDTO,
        opportunity: dict[str, Any],
    ) -> bool:
        """Returns True when user passes hard eligibility."""
        result = self.evaluate_detailed(user_profile, opportunity)
        return result.is_eligible

    def filter_opportunities(
        self,
        user_profile: UserProfileDTO,
        opportunities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Filters opportunities, returning only those passing hard eligibility."""
        return [opp for opp in opportunities if self.evaluate(user_profile, opp)]

    # ------------------------------------------------------------------
    # Private evaluation of individual REQUIRED requirements
    # ------------------------------------------------------------------

    def _evaluate_single_required_criterion(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if req.confidence == ConfidenceLevel.LOW:
            return CriterionEvaluation(
                criterion=req.req_type,
                decision=EligibilityDecision.UNKNOWN,
                reason=f"Low-confidence {req.req_type} requirement extraction; cannot enforce hard exclusion",
                requirement=req,
            )

        if req.req_type == RequirementType.NATIONALITY:
            return self._eval_nationality(user_profile.nationality, req)
        elif req.req_type == RequirementType.EDUCATION:
            return self._eval_education(user_profile.education_level, req)
        elif req.req_type == RequirementType.GPA:
            return self._eval_gpa(user_profile, req)
        elif req.req_type == RequirementType.AGE:
            return self._eval_age(user_profile, req)
        elif req.req_type == RequirementType.LANGUAGE:
            return self._eval_language(user_profile, req)
        elif req.req_type == RequirementType.EXPERIENCE:
            return self._eval_experience(user_profile, req)
        elif req.req_type == RequirementType.FINANCIAL_NEED:
            return self._eval_financial_need(user_profile, req)
        elif req.req_type == RequirementType.FIELD_OF_STUDY:
            return self._eval_field_of_study(user_profile, req)

        return CriterionEvaluation(
            criterion=req.req_type,
            decision=EligibilityDecision.UNKNOWN,
            reason=f"REQUIRED requirement type '{req.req_type}' cannot be reliably evaluated from UserProfileDTO",
            requirement=req,
        )

    def _eval_nationality(
        self,
        user_nationality: str | None,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if not user_nationality:
            return CriterionEvaluation(
                criterion="nationality",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED nationality specified, but user nationality is missing from profile",
                requirement=req,
            )

        if req.value == "open_to_all":
            return CriterionEvaluation(
                criterion="nationality",
                decision=EligibilityDecision.ELIGIBLE,
                reason="Open to all nationalities",
                requirement=req,
            )

        norm_user = (
            self._norm.normalize_country(user_nationality) or user_nationality
        ).lower()
        countries: list[str] = (
            req.value if isinstance(req.value, list) else [str(req.value)]
        )

        if req.condition == RequirementCondition.NOT_IN:
            excluded_lower = [c.lower() for c in countries]
            if norm_user in excluded_lower:
                return CriterionEvaluation(
                    criterion="nationality",
                    decision=EligibilityDecision.INELIGIBLE,
                    reason=f"User nationality '{user_nationality}' matches excluded nationality criteria",
                    requirement=req,
                )
            return CriterionEvaluation(
                criterion="nationality",
                decision=EligibilityDecision.ELIGIBLE,
                reason=f"User nationality '{user_nationality}' satisfies nationality requirement",
                requirement=req,
            )

        normalized_countries = [
            (self._norm.normalize_country(c) or c).lower() for c in countries
        ]
        for tok in OPEN_TO_ALL_NATIONALITIES:
            if tok in [c.lower() for c in countries]:
                return CriterionEvaluation(
                    criterion="nationality",
                    decision=EligibilityDecision.ELIGIBLE,
                    reason="Open to all nationalities",
                    requirement=req,
                )

        if norm_user in normalized_countries:
            return CriterionEvaluation(
                criterion="nationality",
                decision=EligibilityDecision.ELIGIBLE,
                reason=f"User nationality '{user_nationality}' matches required nationalities: {countries[:5]}",
                requirement=req,
            )

        return CriterionEvaluation(
            criterion="nationality",
            decision=EligibilityDecision.INELIGIBLE,
            reason=f"User nationality '{user_nationality}' does not match required nationalities: {countries[:5]}",
            requirement=req,
        )

    def _eval_education(
        self,
        user_education_level: str | None,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if not user_education_level:
            return CriterionEvaluation(
                criterion="education",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED degree level specified, but user education level is missing from profile",
                requirement=req,
            )

        degree_levels: list[str] = (
            req.value if isinstance(req.value, list) else [str(req.value)]
        )
        normalized_levels = self._norm.normalize_study_levels(degree_levels)

        if not normalized_levels:
            return CriterionEvaluation(
                criterion="education",
                decision=EligibilityDecision.UNKNOWN,
                reason="No explicit study levels extracted",
                requirement=req,
            )

        user_rank = _LEVEL_RANK.get(user_education_level, -1)

        for required_level in normalized_levels:
            req_rank = _LEVEL_RANK.get(required_level, -1)
            if req_rank < 0:
                continue
            if user_rank >= req_rank - 1:
                return CriterionEvaluation(
                    criterion="education",
                    decision=EligibilityDecision.ELIGIBLE,
                    reason=f"User education level '{user_education_level}' satisfies required study levels: {normalized_levels}",
                    requirement=req,
                )

        return CriterionEvaluation(
            criterion="education",
            decision=EligibilityDecision.INELIGIBLE,
            reason=f"User education level '{user_education_level}' does not meet required study levels: {normalized_levels}",
            requirement=req,
        )

    def _eval_gpa(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        user_gpas = [
            edu.gpa_normalized_4
            for edu in user_profile.educations
            if edu.gpa_normalized_4 is not None
        ]
        if not user_gpas:
            return CriterionEvaluation(
                criterion="gpa",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED GPA threshold specified, but user GPA is missing from profile",
                requirement=req,
            )

        user_highest = max(user_gpas)
        val = req.value

        if isinstance(val, dict):
            req_type = val.get("type", "")
            if req_type in ("QUALITATIVE", "HONORS"):
                return CriterionEvaluation(
                    criterion="gpa",
                    decision=EligibilityDecision.UNKNOWN,
                    reason=f"Qualitative REQUIRED GPA '{val.get('honors') or val.get('text')}' cannot be converted without approved taxonomy",
                    requirement=req,
                )

            min_gpa = val.get("min_gpa_normalized_4")
            if min_gpa is not None:
                if user_highest >= min_gpa:
                    return CriterionEvaluation(
                        criterion="gpa",
                        decision=EligibilityDecision.ELIGIBLE,
                        reason=f"User GPA ({user_highest:.2f}) meets required GPA threshold ({min_gpa:.2f})",
                        requirement=req,
                    )
                return CriterionEvaluation(
                    criterion="gpa",
                    decision=EligibilityDecision.INELIGIBLE,
                    reason=f"User GPA ({user_highest:.2f}) is below required GPA threshold ({min_gpa:.2f})",
                    requirement=req,
                )

        return CriterionEvaluation(
            criterion="gpa",
            decision=EligibilityDecision.UNKNOWN,
            reason="GPA requirement value structure not recognized",
            requirement=req,
        )

    def _eval_age(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if user_profile.date_of_birth is None:
            return CriterionEvaluation(
                criterion="age",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED age limit specified, but user date_of_birth is missing from profile",
                requirement=req,
            )

        today = date.today()
        dob = user_profile.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        val = req.value
        if isinstance(val, dict):
            max_age = val.get("maximum")
            min_age = val.get("minimum")

            if max_age is not None and min_age is not None:
                if min_age <= age <= max_age:
                    return CriterionEvaluation(
                        criterion="age",
                        decision=EligibilityDecision.ELIGIBLE,
                        reason=f"User age ({age}) is within required age range [{min_age}-{max_age}]",
                        requirement=req,
                    )
                return CriterionEvaluation(
                    criterion="age",
                    decision=EligibilityDecision.INELIGIBLE,
                    reason=f"User age ({age}) is outside required age range [{min_age}-{max_age}]",
                    requirement=req,
                )

            if max_age is not None:
                if age <= max_age:
                    return CriterionEvaluation(
                        criterion="age",
                        decision=EligibilityDecision.ELIGIBLE,
                        reason=f"User age ({age}) meets maximum age limit ({max_age})",
                        requirement=req,
                    )
                return CriterionEvaluation(
                    criterion="age",
                    decision=EligibilityDecision.INELIGIBLE,
                    reason=f"User age ({age}) exceeds maximum age limit ({max_age})",
                    requirement=req,
                )

            if min_age is not None:
                if age >= min_age:
                    return CriterionEvaluation(
                        criterion="age",
                        decision=EligibilityDecision.ELIGIBLE,
                        reason=f"User age ({age}) meets minimum age limit ({min_age})",
                        requirement=req,
                    )
                return CriterionEvaluation(
                    criterion="age",
                    decision=EligibilityDecision.INELIGIBLE,
                    reason=f"User age ({age}) is below minimum age limit ({min_age})",
                    requirement=req,
                )

        return CriterionEvaluation(
            criterion="age",
            decision=EligibilityDecision.UNKNOWN,
            reason="Age requirement value structure not recognized",
            requirement=req,
        )

    def _eval_language(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        val = req.value
        if isinstance(val, str) and val == "no_certificate_required":
            return CriterionEvaluation(
                criterion="language",
                decision=EligibilityDecision.ELIGIBLE,
                reason="Language certificate waived/not required",
                requirement=req,
            )

        if isinstance(val, dict):
            tests = val.get("tests", [])
            if tests:
                for test_item in tests:
                    test_name = str(test_item.get("test", "")).upper()
                    min_score = test_item.get("min_score")
                    if min_score is None:
                        continue
                    for tr in user_profile.test_results:
                        if (
                            tr.test_name
                            and tr.test_name.upper() == test_name
                            and tr.score is not None
                        ):
                            if tr.score >= min_score:
                                return CriterionEvaluation(
                                    criterion="language",
                                    decision=EligibilityDecision.ELIGIBLE,
                                    reason=f"User {test_name} score ({tr.score}) meets required minimum ({min_score})",
                                    requirement=req,
                                )
                            return CriterionEvaluation(
                                criterion="language",
                                decision=EligibilityDecision.INELIGIBLE,
                                reason=f"User {test_name} score ({tr.score}) is below required minimum ({min_score})",
                                requirement=req,
                            )

            user_langs = [
                lang.name.lower() for lang in user_profile.languages if lang.name
            ]
            if not user_langs and not user_profile.test_results:
                return CriterionEvaluation(
                    criterion="language",
                    decision=EligibilityDecision.UNKNOWN,
                    reason="REQUIRED language test specified, but user test results are missing from profile",
                    requirement=req,
                )

        return CriterionEvaluation(
            criterion="language",
            decision=EligibilityDecision.UNKNOWN,
            reason="REQUIRED language requirement cannot be determined from available profile data",
            requirement=req,
        )

    def _eval_experience(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if req.value == "no_experience_required":
            return CriterionEvaluation(
                criterion="experience",
                decision=EligibilityDecision.ELIGIBLE,
                reason="Experience explicitly not required",
                requirement=req,
            )

        if not user_profile.experiences:
            return CriterionEvaluation(
                criterion="experience",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED experience specified, but user profile experiences list is empty/missing",
                requirement=req,
            )

        val = req.value
        req_area = "relevant_experience"
        if isinstance(val, dict):
            req_area = str(val.get("area") or "relevant_experience")
        elif isinstance(val, str):
            req_area = val

        if _user_has_matching_experience_area(user_profile, req_area):
            return CriterionEvaluation(
                criterion="experience",
                decision=EligibilityDecision.ELIGIBLE,
                reason=f"User experiences match required experience area '{req_area}'",
                requirement=req,
            )

        return CriterionEvaluation(
            criterion="experience",
            decision=EligibilityDecision.INELIGIBLE,
            reason=f"User experiences {user_profile.experiences[:3]} do not match required experience area '{req_area}'",
            requirement=req,
        )

    def _eval_financial_need(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if user_profile.has_financial_need is None:
            return CriterionEvaluation(
                criterion="financial_need",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED financial need specified, but user has_financial_need is missing from profile",
                requirement=req,
            )
        if user_profile.has_financial_need:
            return CriterionEvaluation(
                criterion="financial_need",
                decision=EligibilityDecision.ELIGIBLE,
                reason="User has_financial_need=True satisfies requirement",
                requirement=req,
            )
        return CriterionEvaluation(
            criterion="financial_need",
            decision=EligibilityDecision.INELIGIBLE,
            reason="User has_financial_need=False fails required financial need criterion",
            requirement=req,
        )

    def _eval_field_of_study(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> CriterionEvaluation:
        if req.value == "open_to_all":
            return CriterionEvaluation(
                criterion="field_of_study",
                decision=EligibilityDecision.ELIGIBLE,
                reason="Field of study open to all",
                requirement=req,
            )
        user_fields = [f.name.lower() for f in user_profile.fields_of_study if f.name]
        user_majors = [e.major.lower() for e in user_profile.educations if e.major]
        all_user_disciplines = user_fields + user_majors

        if not all_user_disciplines:
            return CriterionEvaluation(
                criterion="field_of_study",
                decision=EligibilityDecision.UNKNOWN,
                reason="REQUIRED field of study specified, but user fields_of_study and majors are missing from profile",
                requirement=req,
            )

        req_fields = req.value if isinstance(req.value, list) else [str(req.value)]
        for rfield in req_fields:
            rf_lower = str(rfield).lower()
            for udisc in all_user_disciplines:
                if rf_lower == udisc:
                    return CriterionEvaluation(
                        criterion="field_of_study",
                        decision=EligibilityDecision.ELIGIBLE,
                        reason=f"User field/major '{udisc}' exactly matches required field '{rfield}'",
                        requirement=req,
                    )

        return CriterionEvaluation(
            criterion="field_of_study",
            decision=EligibilityDecision.INELIGIBLE,
            reason=f"User fields {all_user_disciplines[:3]} do not match required fields {req_fields[:3]}",
            requirement=req,
        )
