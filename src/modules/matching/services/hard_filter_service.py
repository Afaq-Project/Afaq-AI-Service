from typing import Any

from src.modules.scraping.services.normalization_service import NormalizationService

OPEN_TO_ALL_NATIONALITIES = {
    "all",
    "all nationalities",
    "international",
    "any nationality",
    "جميع الجنسيات",
    "كافة الجنسيات",
    "مفتوح للجميع",
}


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
        self, normalization_service: NormalizationService | None = None
    ) -> None:
        self.normalizer = normalization_service or NormalizationService()

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
