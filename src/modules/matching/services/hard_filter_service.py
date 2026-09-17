from typing import Any

from src.modules.matching.models import (
    OPEN_TO_ALL_NATIONALITIES,
    ConfidenceLevel,
    CriterionEvaluation,
    EligibilityDecision,
    ExtractedRequirement,
    HardFilterResultDTO,
    OpportunityRequirementsDTO,
    RequirementStatus,
    RequirementType,
)
from src.modules.matching.services.requirement_extractor import (
    RequirementExtractor,
)
from src.modules.scraping.services.normalization_service import NormalizationService


def passes_nationality_filter(
    user_nationality: str | None,
    eligible_nationalities: list[str] | str | None,
    normalizer: NormalizationService | None = None,
) -> bool:
    """Evaluates nationality eligibility against opportunity requirements.

    Rules:
    - Case 1 (No restriction): If eligible_nationalities is missing/empty -> PASS.
    - Case 3 (Open to all): If eligible_nationalities contains a canonical open-to-all value -> PASS.
    - Case 2 (Explicit restriction):
        - User nationality is missing/empty -> FAIL.
        - User nationality matches one of the eligible nationalities -> PASS.
        - User nationality does not match -> FAIL.
    """
    if eligible_nationalities is None:
        return True

    if isinstance(eligible_nationalities, str):
        cleaned_str = eligible_nationalities.strip()
        if not cleaned_str:
            return True
        raw_items = [cleaned_str]
    elif isinstance(eligible_nationalities, list):
        if not eligible_nationalities:
            return True
        raw_items = eligible_nationalities
    else:
        return True

    valid_items = [
        str(item).strip()
        for item in raw_items
        if item is not None and str(item).strip()
    ]
    if not valid_items:
        return True

    # Case 3: Canonical Open-to-All exact match (case-insensitive)
    for item in valid_items:
        if item.lower() in OPEN_TO_ALL_NATIONALITIES:
            return True

    # Case 2: Explicit restriction exists -> user nationality is mandatory
    if not user_nationality or not str(user_nationality).strip():
        return False

    norm = normalizer or NormalizationService()
    user_nat_clean = str(user_nationality).strip()
    user_nat_norm = norm.normalize_country(user_nat_clean)
    user_nat_lower = user_nat_clean.lower()

    for item in valid_items:
        item_clean = str(item).strip()
        item_norm = norm.normalize_country(item_clean)
        item_lower = item_clean.lower()

        # Compare normalized standard forms if available
        if user_nat_norm and item_norm and user_nat_norm.lower() == item_norm.lower():
            return True

        # Fallback exact case-insensitive match
        if user_nat_lower == item_lower:
            return True

    return False


def passes_education_filter(
    user_education_level: str | None,
    required_study_levels: list[str] | str | None,
    normalizer: NormalizationService | None = None,
) -> bool:
    """Evaluates strict education-level eligibility against opportunity requirements.

    Rules:
    - If opportunity has no study level requirements (missing/empty) -> PASS.
    - If opportunity requires one or more study levels:
        - User education level is missing/empty -> FAIL.
        - User education level matches ANY required study level -> PASS.
        - User education level matches none -> FAIL.
    """
    if required_study_levels is None:
        return True

    if isinstance(required_study_levels, str):
        cleaned_str = required_study_levels.strip()
        if not cleaned_str:
            return True
        raw_levels = [cleaned_str]
    elif isinstance(required_study_levels, list):
        if not required_study_levels:
            return True
        raw_levels = required_study_levels
    else:
        return True

    valid_req_levels = [
        str(lvl).strip() for lvl in raw_levels if lvl is not None and str(lvl).strip()
    ]
    if not valid_req_levels:
        return True

    # Explicit study level requirement exists -> user education is mandatory
    if not user_education_level or not str(user_education_level).strip():
        return False

    norm = normalizer or NormalizationService()
    user_edu_clean = str(user_education_level).strip()
    user_levels_norm = norm.normalize_study_levels([user_edu_clean.replace("_", " ")])

    cleaned_req_levels = [lvl.replace("_", " ") for lvl in valid_req_levels]
    norm_required = norm.normalize_study_levels(cleaned_req_levels)
    req_set = (
        set(norm_required)
        if norm_required
        else {lvl.lower() for lvl in valid_req_levels}
    )

    if user_levels_norm:
        if any(lvl in req_set for lvl in user_levels_norm):
            return True
    else:
        # Fallback comparison if not mapped by standard regex patterns
        user_lower = user_edu_clean.lower()
        valid_lower_set = {lvl.lower() for lvl in valid_req_levels} | {
            lvl.lower() for lvl in cleaned_req_levels
        }
        if user_lower in valid_lower_set:
            return True

    return False


def _evaluate_single_nationality_req(
    user_nationality: str | None,
    req: ExtractedRequirement | None,
    norm: NormalizationService,
) -> CriterionEvaluation:
    category = "nationality"
    if req is None:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.ELIGIBLE,
            requirement_status=RequirementStatus.NOT_REQUIRED,
            reason="No explicit nationality restriction found in opportunity",
            evidence=None,
            confidence=ConfidenceLevel.HIGH,
        )

    if req.status == RequirementStatus.UNKNOWN:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.UNKNOWN,
            requirement_status=RequirementStatus.UNKNOWN,
            reason="No explicit nationality restriction found in opportunity",
            evidence=req.evidence,
            confidence=req.confidence,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.ELIGIBLE,
            requirement_status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity is explicitly open to all nationalities",
            evidence=req.evidence,
            confidence=req.confidence,
        )

    if req.status == RequirementStatus.REQUIRED:
        # Handle compound conditions if present
        if req.conditions and req.conditions.items:
            cond_op = req.conditions.operator.upper()
            cond_evals = [
                _evaluate_single_nationality_req(
                    user_nationality,
                    (
                        item
                        if isinstance(item, ExtractedRequirement)
                        else ExtractedRequirement(**item)
                    ),
                    norm,
                )
                for item in req.conditions.items
            ]
            if cond_op == "AND":
                if any(
                    c.decision == EligibilityDecision.INELIGIBLE for c in cond_evals
                ):
                    ineligible_c = next(
                        c
                        for c in cond_evals
                        if c.decision == EligibilityDecision.INELIGIBLE
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.INELIGIBLE,
                        requirement_status=req.status,
                        reason=ineligible_c.reason,
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                elif all(
                    c.decision == EligibilityDecision.ELIGIBLE for c in cond_evals
                ):
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.ELIGIBLE,
                        requirement_status=req.status,
                        reason="All compound nationality requirements satisfied",
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                else:
                    unknown_c = next(
                        (
                            c
                            for c in cond_evals
                            if c.decision == EligibilityDecision.UNKNOWN
                        ),
                        None,
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.UNKNOWN,
                        requirement_status=req.status,
                        reason=(
                            unknown_c.reason
                            if unknown_c
                            else "Compound nationality requirements undetermined"
                        ),
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
            elif cond_op == "OR":
                if any(c.decision == EligibilityDecision.ELIGIBLE for c in cond_evals):
                    eligible_c = next(
                        c
                        for c in cond_evals
                        if c.decision == EligibilityDecision.ELIGIBLE
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.ELIGIBLE,
                        requirement_status=req.status,
                        reason=eligible_c.reason,
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                elif all(
                    c.decision == EligibilityDecision.INELIGIBLE for c in cond_evals
                ):
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.INELIGIBLE,
                        requirement_status=req.status,
                        reason="User does not satisfy any of the alternative nationality requirements",
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                else:
                    unknown_c = next(
                        (
                            c
                            for c in cond_evals
                            if c.decision == EligibilityDecision.UNKNOWN
                        ),
                        None,
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.UNKNOWN,
                        requirement_status=req.status,
                        reason=(
                            unknown_c.reason
                            if unknown_c
                            else "Alternative nationality requirements undetermined"
                        ),
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )

        # Low confidence extracted requirement -> UNKNOWN (never hard exclusion)
        if req.confidence == ConfidenceLevel.LOW:
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.REQUIRED,
                reason="Low-confidence nationality requirement extraction; cannot enforce hard exclusion",
                evidence=req.evidence,
                confidence=req.confidence,
            )

        # If user nationality is missing -> UNKNOWN (not INELIGIBLE)
        if not user_nationality or not str(user_nationality).strip():
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.REQUIRED,
                reason="Opportunity requires specific nationality, but user nationality is not provided in profile",
                evidence=req.evidence,
                confidence=req.confidence,
            )

        user_nat_clean = str(user_nationality).strip()
        user_nat_norm = norm.normalize_country(user_nat_clean)
        user_nat_lower = user_nat_clean.lower()

        val = req.value or {}
        countries: list[str] = []
        if isinstance(val, dict):
            if "countries" in val and isinstance(val["countries"], list):
                countries = [str(c).strip() for c in val["countries"] if str(c).strip()]
            elif "description" in val:
                desc = str(val["description"]).lower()
                if user_nat_lower in desc or (
                    user_nat_norm and user_nat_norm.lower() in desc
                ):
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.ELIGIBLE,
                        requirement_status=RequirementStatus.REQUIRED,
                        reason=f"User nationality '{user_nationality}' matches required nationality criteria",
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
        elif isinstance(val, list):
            countries = [str(c).strip() for c in val if str(c).strip()]

        if countries:
            matched = False
            for item in countries:
                item_clean = str(item).strip()
                item_norm = norm.normalize_country(item_clean)
                item_lower = item_clean.lower()
                if (
                    user_nat_norm
                    and item_norm
                    and user_nat_norm.lower() == item_norm.lower()
                ):
                    matched = True
                    break
                if user_nat_lower == item_lower:
                    matched = True
                    break

            if matched:
                return CriterionEvaluation(
                    category=category,
                    decision=EligibilityDecision.ELIGIBLE,
                    requirement_status=RequirementStatus.REQUIRED,
                    reason=f"User nationality '{user_nationality}' matches required nationalities: {countries}",
                    evidence=req.evidence,
                    confidence=req.confidence,
                )
            else:
                return CriterionEvaluation(
                    category=category,
                    decision=EligibilityDecision.INELIGIBLE,
                    requirement_status=RequirementStatus.REQUIRED,
                    reason=f"User nationality '{user_nationality}' does not match required nationalities: {countries}",
                    evidence=req.evidence,
                    confidence=req.confidence,
                )

        if req.evidence and (
            user_nat_lower in req.evidence.lower()
            or (user_nat_norm and user_nat_norm.lower() in req.evidence.lower())
        ):
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.ELIGIBLE,
                requirement_status=RequirementStatus.REQUIRED,
                reason=f"User nationality '{user_nationality}' matches eligibility requirement evidence",
                evidence=req.evidence,
                confidence=req.confidence,
            )

        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.INELIGIBLE,
            requirement_status=RequirementStatus.REQUIRED,
            reason=f"User nationality '{user_nationality}' does not match nationality requirement",
            evidence=req.evidence,
            confidence=req.confidence,
        )

    return CriterionEvaluation(
        category=category,
        decision=EligibilityDecision.UNKNOWN,
        requirement_status=req.status,
        reason="Nationality requirement status is undetermined",
        evidence=req.evidence,
        confidence=req.confidence,
    )


def _evaluate_single_education_req(
    user_education_level: str | None,
    req: ExtractedRequirement | None,
    norm: NormalizationService,
) -> CriterionEvaluation:
    category = "education"
    if req is None:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.ELIGIBLE,
            requirement_status=RequirementStatus.NOT_REQUIRED,
            reason="No explicit education level restriction found in opportunity",
            evidence=None,
            confidence=ConfidenceLevel.HIGH,
        )

    if req.status == RequirementStatus.UNKNOWN:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.UNKNOWN,
            requirement_status=RequirementStatus.UNKNOWN,
            reason="No explicit education level restriction found in opportunity",
            evidence=req.evidence,
            confidence=req.confidence,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CriterionEvaluation(
            category=category,
            decision=EligibilityDecision.ELIGIBLE,
            requirement_status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no degree level restrictions",
            evidence=req.evidence,
            confidence=req.confidence,
        )

    if req.status == RequirementStatus.REQUIRED:
        # Handle compound conditions if present
        if req.conditions and req.conditions.items:
            cond_op = req.conditions.operator.upper()
            cond_evals = [
                _evaluate_single_education_req(
                    user_education_level,
                    (
                        item
                        if isinstance(item, ExtractedRequirement)
                        else ExtractedRequirement(**item)
                    ),
                    norm,
                )
                for item in req.conditions.items
            ]
            if cond_op == "AND":
                if any(
                    c.decision == EligibilityDecision.INELIGIBLE for c in cond_evals
                ):
                    ineligible_c = next(
                        c
                        for c in cond_evals
                        if c.decision == EligibilityDecision.INELIGIBLE
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.INELIGIBLE,
                        requirement_status=req.status,
                        reason=ineligible_c.reason,
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                elif all(
                    c.decision == EligibilityDecision.ELIGIBLE for c in cond_evals
                ):
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.ELIGIBLE,
                        requirement_status=req.status,
                        reason="All compound education requirements satisfied",
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                else:
                    unknown_c = next(
                        (
                            c
                            for c in cond_evals
                            if c.decision == EligibilityDecision.UNKNOWN
                        ),
                        None,
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.UNKNOWN,
                        requirement_status=req.status,
                        reason=(
                            unknown_c.reason
                            if unknown_c
                            else "Compound education requirements undetermined"
                        ),
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
            elif cond_op == "OR":
                if any(c.decision == EligibilityDecision.ELIGIBLE for c in cond_evals):
                    eligible_c = next(
                        c
                        for c in cond_evals
                        if c.decision == EligibilityDecision.ELIGIBLE
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.ELIGIBLE,
                        requirement_status=req.status,
                        reason=eligible_c.reason,
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                elif all(
                    c.decision == EligibilityDecision.INELIGIBLE for c in cond_evals
                ):
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.INELIGIBLE,
                        requirement_status=req.status,
                        reason="User does not satisfy any of the alternative education requirements",
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )
                else:
                    unknown_c = next(
                        (
                            c
                            for c in cond_evals
                            if c.decision == EligibilityDecision.UNKNOWN
                        ),
                        None,
                    )
                    return CriterionEvaluation(
                        category=category,
                        decision=EligibilityDecision.UNKNOWN,
                        requirement_status=req.status,
                        reason=(
                            unknown_c.reason
                            if unknown_c
                            else "Alternative education requirements undetermined"
                        ),
                        evidence=req.evidence,
                        confidence=req.confidence,
                    )

        if req.confidence == ConfidenceLevel.LOW:
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.REQUIRED,
                reason="Low-confidence education requirement extraction; cannot enforce hard exclusion",
                evidence=req.evidence,
                confidence=req.confidence,
            )

        if not user_education_level or not str(user_education_level).strip():
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.REQUIRED,
                reason="Opportunity requires specific degree level, but user education level is not provided in profile",
                evidence=req.evidence,
                confidence=req.confidence,
            )

        user_edu_clean = str(user_education_level).strip()
        user_levels_norm = norm.normalize_study_levels(
            [user_edu_clean.replace("_", " ")]
        )

        val = req.value or {}
        degree_levels: list[str] = []
        if isinstance(val, dict) and "degree_levels" in val:
            degree_levels = val["degree_levels"]
        elif isinstance(val, list):
            degree_levels = val

        norm_required = norm.normalize_study_levels(
            [lvl.replace("_", " ") for lvl in degree_levels]
        )
        req_set = (
            set(norm_required)
            if norm_required
            else {lvl.lower() for lvl in degree_levels}
        )

        matched = False
        if user_levels_norm:
            if any(lvl in req_set for lvl in user_levels_norm):
                matched = True
        else:
            user_lower = user_edu_clean.lower()
            valid_lower_set = {lvl.lower() for lvl in degree_levels}
            if user_lower in valid_lower_set:
                matched = True

        if matched:
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.ELIGIBLE,
                requirement_status=RequirementStatus.REQUIRED,
                reason=f"User education level '{user_education_level}' matches required study levels: {degree_levels}",
                evidence=req.evidence,
                confidence=req.confidence,
            )
        else:
            return CriterionEvaluation(
                category=category,
                decision=EligibilityDecision.INELIGIBLE,
                requirement_status=RequirementStatus.REQUIRED,
                reason=f"User education level '{user_education_level}' does not match required study levels: {degree_levels}",
                evidence=req.evidence,
                confidence=req.confidence,
            )

    return CriterionEvaluation(
        category=category,
        decision=EligibilityDecision.UNKNOWN,
        requirement_status=req.status,
        reason="Education requirement status is undetermined",
        evidence=req.evidence,
        confidence=req.confidence,
    )


def evaluate_hard_filters(
    user_profile: Any,
    opportunity: Any,
    normalizer: NormalizationService | None = None,
) -> bool:
    """Evaluates combined nationality and education hard filters for a user and opportunity.

    Returns True if BOTH nationality and education filters pass; False otherwise.
    Leaves user profile and opportunity objects unmutated.
    """
    if isinstance(user_profile, dict):
        user_nat = user_profile.get("nationality")
        user_edu = user_profile.get("education_level")
    else:
        user_nat = getattr(user_profile, "nationality", None)
        user_edu = getattr(user_profile, "education_level", None)

    if isinstance(opportunity, dict):
        eligibility = opportunity.get("eligibility") or {}
        eligible_nats = (
            eligibility.get("eligible_nationalities")
            if isinstance(eligibility, dict)
            else None
        )
        study_levels = opportunity.get("study_levels")
    else:
        eligibility = getattr(opportunity, "eligibility", None) or {}
        eligible_nats = (
            eligibility.get("eligible_nationalities")
            if isinstance(eligibility, dict)
            else None
        )
        study_levels = getattr(opportunity, "study_levels", None)

    nat_pass = passes_nationality_filter(user_nat, eligible_nats, normalizer=normalizer)
    if not nat_pass:
        return False

    edu_pass = passes_education_filter(user_edu, study_levels, normalizer=normalizer)
    if not edu_pass:
        return False

    return True


def filter_by_hard_eligibility(
    user_profile: Any,
    opportunities: list[Any],
    normalizer: NormalizationService | None = None,
) -> list[Any]:
    """Filters a collection of opportunities, returning only those passing hard eligibility filters.

    Does NOT mutate input objects.
    """
    norm = normalizer or NormalizationService()
    return [
        opp
        for opp in opportunities
        if evaluate_hard_filters(user_profile, opp, normalizer=norm)
    ]


class HardFilterService:
    """Service providing deterministic nationality and strict education-level hard filtering."""

    def __init__(
        self,
        normalization_service: NormalizationService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self.normalizer = normalization_service or NormalizationService()
        self.extractor = requirement_extractor or RequirementExtractor(
            normalization_service=self.normalizer
        )

    def passes_nationality(
        self,
        user_nationality: str | None,
        eligible_nationalities: list[str] | str | None,
    ) -> bool:
        return passes_nationality_filter(
            user_nationality, eligible_nationalities, normalizer=self.normalizer
        )

    def passes_education(
        self,
        user_education_level: str | None,
        required_study_levels: list[str] | str | None,
    ) -> bool:
        return passes_education_filter(
            user_education_level,
            required_study_levels,
            normalizer=self.normalizer,
        )

    def evaluate_detailed(
        self,
        user_profile: Any,
        opportunity_or_requirements: Any,
    ) -> HardFilterResultDTO:
        """Evaluates structured hard requirements (nationality and education) for a user.

        Produces an explainable HardFilterResultDTO with explicit decision
        (ELIGIBLE, INELIGIBLE, UNKNOWN), criteria evaluations, and failure/unknown reasons.
        Missing user data or missing opportunity requirements result in UNKNOWN,
        which does NOT cause hard exclusion (is_eligible = True).
        """
        if isinstance(user_profile, dict):
            user_nat = user_profile.get("nationality")
            user_edu = user_profile.get("education_level")
        else:
            user_nat = getattr(user_profile, "nationality", None)
            user_edu = getattr(user_profile, "education_level", None)

        if isinstance(opportunity_or_requirements, OpportunityRequirementsDTO):
            req_dto = opportunity_or_requirements
        else:
            req_dto = self.extractor.extract_requirements(opportunity_or_requirements)

        # 1. Evaluate Nationality
        nat_req = req_dto.get_first_by_category("nationality")
        # Ensure only ELIGIBILITY requirement type is hard-filtered
        if nat_req and nat_req.requirement_type != RequirementType.ELIGIBILITY:
            nat_eval = CriterionEvaluation(
                category="nationality",
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.UNKNOWN,
                reason="Non-eligibility nationality requirement ignored for hard filtering",
                evidence=nat_req.evidence,
                confidence=nat_req.confidence,
            )
        else:
            nat_eval = _evaluate_single_nationality_req(
                user_nat, nat_req, self.normalizer
            )

        # 2. Evaluate Education
        edu_req = req_dto.get_first_by_category("education")
        if edu_req and edu_req.requirement_type != RequirementType.ELIGIBILITY:
            edu_eval = CriterionEvaluation(
                category="education",
                decision=EligibilityDecision.UNKNOWN,
                requirement_status=RequirementStatus.UNKNOWN,
                reason="Non-eligibility education requirement ignored for hard filtering",
                evidence=edu_req.evidence,
                confidence=edu_req.confidence,
            )
        else:
            edu_eval = _evaluate_single_education_req(
                user_edu, edu_req, self.normalizer
            )

        criteria: dict[str, CriterionEvaluation] = {
            "nationality": nat_eval,
            "education": edu_eval,
        }

        failure_reasons = [
            c.reason
            for c in criteria.values()
            if c.decision == EligibilityDecision.INELIGIBLE
        ]
        unknown_reasons = [
            c.reason
            for c in criteria.values()
            if c.decision == EligibilityDecision.UNKNOWN
        ]

        if any(c.decision == EligibilityDecision.INELIGIBLE for c in criteria.values()):
            overall_decision = EligibilityDecision.INELIGIBLE
            is_eligible = False
        elif all(c.decision == EligibilityDecision.ELIGIBLE for c in criteria.values()):
            overall_decision = EligibilityDecision.ELIGIBLE
            is_eligible = True
        else:
            overall_decision = EligibilityDecision.UNKNOWN
            is_eligible = True  # UNKNOWN does not cause hard exclusion

        return HardFilterResultDTO(
            decision=overall_decision,
            is_eligible=is_eligible,
            criteria=criteria,
            failure_reasons=failure_reasons,
            unknown_reasons=unknown_reasons,
            requirements=req_dto,
        )

    def evaluate(self, user_profile: Any, opportunity: Any) -> bool:
        return evaluate_hard_filters(
            user_profile, opportunity, normalizer=self.normalizer
        )

    def filter_opportunities(
        self, user_profile: Any, opportunities: list[Any]
    ) -> list[Any]:
        return filter_by_hard_eligibility(
            user_profile, opportunities, normalizer=self.normalizer
        )
