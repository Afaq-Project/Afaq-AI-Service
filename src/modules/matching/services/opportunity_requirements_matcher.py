"""Opportunity Requirements Matcher for Afaq AI Matching Engine.

Evaluates extracted scholarship requirements against normalized UserProfileDTO.
Implements the 25% Opportunity Requirements Match category with zero double-counting
and complete explainability.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.matching.models import (
    CategoryScoreDTO,
    ExtractedRequirement,
    OpportunityRequirementsDTO,
    RequirementStatus,
    RequirementType,
    UserProfileDTO,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor
from src.modules.scraping.services.normalization_service import NormalizationService


class RequirementMatchDecision(StrEnum):
    """Decision status for an individual requirement evaluation."""

    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    NEUTRAL_NOT_REQUIRED = "NEUTRAL_NOT_REQUIRED"
    NEUTRAL_UNKNOWN = "NEUTRAL_UNKNOWN"
    NEUTRAL_MISSING_USER_DATA = "NEUTRAL_MISSING_USER_DATA"
    EXCLUDED_HARD_FILTER = "EXCLUDED_HARD_FILTER"


class SingleRequirementEvaluation(BaseModel):
    """Explainable evaluation result for one requirement."""

    model_config = ConfigDict(extra="ignore")

    req_type: RequirementType
    status: RequirementStatus
    decision: RequirementMatchDecision
    is_soft_candidate: bool
    explanation: str
    requirement: ExtractedRequirement | None = None


class OpportunityRequirementsMatchResult(BaseModel):
    """Complete evaluation result for Opportunity Requirements Match."""

    model_config = ConfigDict(extra="ignore")

    category: str = "opportunity_requirements"
    weight: float = 25.0
    score: float | None = None
    is_applicable: bool = True
    evaluations: list[SingleRequirementEvaluation] = Field(default_factory=list)
    reason: str = ""


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


STANDALONE_CATEGORY_TYPES: frozenset[RequirementType] = frozenset(
    {
        RequirementType.FIELD_OF_STUDY,
        RequirementType.GPA,
        RequirementType.LANGUAGE,
        RequirementType.EXPERIENCE,
    }
)


def _get_requirement_sub_key(req: ExtractedRequirement) -> str | None:
    """Returns sub_key for (req_type, sub_key) requirement grouping."""
    val = req.value
    if req.req_type == RequirementType.GPA:
        return None
    elif req.req_type == RequirementType.LANGUAGE:
        if isinstance(val, dict):
            tests = val.get("tests", [])
            if tests and isinstance(tests, list):
                names = [
                    str(t.get("test") or "").upper() for t in tests if t.get("test")
                ]
                if names:
                    return ",".join(sorted(names))
        return "GENERAL"
    elif req.req_type == RequirementType.EXPERIENCE:
        if isinstance(val, dict):
            return str(val.get("area") or "relevant_experience").lower()
        if isinstance(val, str):
            return val.lower()
        return "relevant_experience"
    elif req.req_type == RequirementType.FIELD_OF_STUDY:
        if isinstance(val, list):
            return ",".join(sorted(str(x).lower() for x in val))
        if isinstance(val, str):
            return val.lower()
        return None
    return None


class OpportunityRequirementsMatcher:
    """Evaluates extracted requirements against UserProfileDTO.

    Rules:
    1. REQUIRED requirements for hard-eligibility fields
       are EXCLUDED from soft score calculation (prevents double-counting).
    2. Same-key PREFERRED requirements (sharing (req_type, sub_key) with REQUIRED)
       are consolidated into standalone categories and EXCLUDED from soft score.
    3. Different-key PREFERRED and Non-category PREFERRED requirements are evaluated in ORM.
    4. NOT_REQUIRED and UNKNOWN requirements are treated as neutral.
    5. Missing user data is treated as neutral (never causes failure).
    """

    def __init__(
        self,
        normalization_service: NormalizationService | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self._norm = normalization_service or NormalizationService()
        self._extractor = requirement_extractor or RequirementExtractor(self._norm)

    def evaluate(
        self,
        user_profile: UserProfileDTO,
        opportunity_or_requirements: dict[str, Any] | OpportunityRequirementsDTO,
    ) -> OpportunityRequirementsMatchResult:
        """Evaluates opportunity requirements against user profile."""
        if isinstance(opportunity_or_requirements, OpportunityRequirementsDTO):
            reqs = opportunity_or_requirements
        else:
            reqs = self._extractor.extract(opportunity_or_requirements)

        # Collect required grouping keys
        required_keys: set[tuple[RequirementType, str | None]] = set()
        for r in reqs.requirements:
            if r.status == RequirementStatus.REQUIRED:
                sub_key = _get_requirement_sub_key(r)
                required_keys.add((r.req_type, sub_key))

        evaluations: list[SingleRequirementEvaluation] = []

        for req in reqs.requirements:
            eval_item = self._evaluate_single_requirement(
                user_profile, req, required_keys
            )
            evaluations.append(eval_item)

        # Soft candidates are PREFERRED requirements not excluded by consolidation or hard filter rules
        soft_candidates = [ev for ev in evaluations if ev.is_soft_candidate]

        if not soft_candidates:
            return OpportunityRequirementsMatchResult(
                score=None,
                is_applicable=False,
                evaluations=evaluations,
                reason="Scholarship text contains no PREFERRED requirements (category not applicable at scholarship level)",
            )

        matched_count = sum(
            1
            for ev in soft_candidates
            if ev.decision == RequirementMatchDecision.MATCHED
        )
        total_candidates = len(soft_candidates)
        score = (matched_count / total_candidates) * 100.0
        reason_msg = (
            f"Matched {matched_count}/{total_candidates} PREFERRED requirements "
            f"({score:.1f}% soft score)"
        )

        return OpportunityRequirementsMatchResult(
            score=round(score, 2),
            is_applicable=True,
            evaluations=evaluations,
            reason=reason_msg,
        )

    def to_category_score_dto(
        self,
        user_profile: UserProfileDTO,
        opportunity_or_requirements: dict[str, Any] | OpportunityRequirementsDTO,
    ) -> CategoryScoreDTO:
        """Converts result to standard CategoryScoreDTO for match calculator integration."""
        res = self.evaluate(user_profile, opportunity_or_requirements)
        return CategoryScoreDTO(
            category=res.category,
            weight=res.weight,
            score=res.score,
            is_applicable=res.is_applicable,
            reason=res.reason,
        )

    # ------------------------------------------------------------------
    # Private evaluation logic per requirement
    # ------------------------------------------------------------------

    def _evaluate_single_requirement(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
        required_keys: set[tuple[RequirementType, str | None]] | None = None,
    ) -> SingleRequirementEvaluation:
        # Rule 1: Exclude ALL REQUIRED requirements from soft score (handled by HardFilterService as hard eligibility)
        if req.status == RequirementStatus.REQUIRED:
            return SingleRequirementEvaluation(
                req_type=req.req_type,
                status=req.status,
                decision=RequirementMatchDecision.EXCLUDED_HARD_FILTER,
                is_soft_candidate=False,
                explanation=f"REQUIRED {req.req_type} is a mandatory eligibility requirement evaluated by HardFilterService — excluded from soft score to prevent double-counting",
                requirement=req,
            )

        # Rule 2: NOT_REQUIRED is neutral
        if req.status == RequirementStatus.NOT_REQUIRED:
            return SingleRequirementEvaluation(
                req_type=req.req_type,
                status=req.status,
                decision=RequirementMatchDecision.NEUTRAL_NOT_REQUIRED,
                is_soft_candidate=False,
                explanation=f"{req.req_type} explicitly NOT_REQUIRED (neutral)",
                requirement=req,
            )

        # Rule 3: UNKNOWN status is neutral
        if req.status == RequirementStatus.UNKNOWN:
            return SingleRequirementEvaluation(
                req_type=req.req_type,
                status=req.status,
                decision=RequirementMatchDecision.NEUTRAL_UNKNOWN,
                is_soft_candidate=False,
                explanation=f"{req.req_type} status UNKNOWN (neutral)",
                requirement=req,
            )

        # Rule 4: Check requirement consolidation for same-key PREFERRED requirements in standalone categories
        if req.status == RequirementStatus.PREFERRED and required_keys is not None:
            sub_key = _get_requirement_sub_key(req)
            if (
                req.req_type in STANDALONE_CATEGORY_TYPES
                and (req.req_type, sub_key) in required_keys
            ):
                return SingleRequirementEvaluation(
                    req_type=req.req_type,
                    status=req.status,
                    decision=RequirementMatchDecision.EXCLUDED_HARD_FILTER,
                    is_soft_candidate=False,
                    explanation=f"PREFERRED {req.req_type} (sub_key='{sub_key}') is consolidated into standalone category evaluator — excluded from ORM to prevent double-counting",
                    requirement=req,
                )

        # Rule 5: Non-consolidated PREFERRED requirements are evaluated for soft score
        is_soft = req.status == RequirementStatus.PREFERRED

        # Delegate evaluation by requirement type
        decision, explanation = self._eval_req_value(user_profile, req)

        return SingleRequirementEvaluation(
            req_type=req.req_type,
            status=req.status,
            decision=decision,
            is_soft_candidate=is_soft,
            explanation=explanation,
            requirement=req,
        )

    def _eval_req_value(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if req.req_type == RequirementType.GPA:
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
        elif req.req_type == RequirementType.NATIONALITY:
            return self._eval_nationality(user_profile, req)

        return (
            RequirementMatchDecision.NEUTRAL_UNKNOWN,
            f"Requirement type '{req.req_type}' not comparable with current user profile fields",
        )

    def _eval_gpa(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        user_gpas = [
            edu.gpa_normalized_4
            for edu in user_profile.educations
            if edu.gpa_normalized_4 is not None
        ]
        if not user_gpas:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "GPA requirement present but user GPA data is missing from profile (neutral)",
            )

        user_highest = max(user_gpas)
        val = req.value

        if isinstance(val, dict):
            min_gpa = val.get("min_gpa_normalized_4")
            if min_gpa is not None:
                if user_highest >= min_gpa:
                    return (
                        RequirementMatchDecision.MATCHED,
                        f"User GPA ({user_highest:.2f}) meets or exceeds required/preferred GPA ({min_gpa:.2f})",
                    )
                return (
                    RequirementMatchDecision.NOT_MATCHED,
                    f"User GPA ({user_highest:.2f}) is below required/preferred GPA ({min_gpa:.2f})",
                )

        return (
            RequirementMatchDecision.NEUTRAL_UNKNOWN,
            "Qualitative GPA requirement cannot be evaluated numerically without conversion scale",
        )

    def _eval_age(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if user_profile.date_of_birth is None:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "Age limit present but user date of birth is missing from profile (neutral)",
            )

        from datetime import date

        today = date.today()
        dob = user_profile.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        val = req.value
        if isinstance(val, dict):
            max_age = val.get("maximum")
            min_age = val.get("minimum")

            if max_age is not None and min_age is not None:
                if min_age <= age <= max_age:
                    return (
                        RequirementMatchDecision.MATCHED,
                        f"User age ({age}) is within age range [{min_age}-{max_age}]",
                    )
                return (
                    RequirementMatchDecision.NOT_MATCHED,
                    f"User age ({age}) is outside age range [{min_age}-{max_age}]",
                )

            if max_age is not None:
                if age <= max_age:
                    return (
                        RequirementMatchDecision.MATCHED,
                        f"User age ({age}) satisfies maximum age limit ({max_age})",
                    )
                return (
                    RequirementMatchDecision.NOT_MATCHED,
                    f"User age ({age}) exceeds maximum age limit ({max_age})",
                )

            if min_age is not None:
                if age >= min_age:
                    return (
                        RequirementMatchDecision.MATCHED,
                        f"User age ({age}) satisfies minimum age limit ({min_age})",
                    )
                return (
                    RequirementMatchDecision.NOT_MATCHED,
                    f"User age ({age}) is below minimum age limit ({min_age})",
                )

        return (
            RequirementMatchDecision.NEUTRAL_UNKNOWN,
            "Age requirement value structure not recognized",
        )

    def _eval_language(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        val = req.value
        if isinstance(val, str) and val == "no_certificate_required":
            return (
                RequirementMatchDecision.MATCHED,
                "Language certificate waived/not required",
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
                                return (
                                    RequirementMatchDecision.MATCHED,
                                    f"User {test_name} score ({tr.score}) meets requirement ({min_score})",
                                )
                            return (
                                RequirementMatchDecision.NOT_MATCHED,
                                f"User {test_name} score ({tr.score}) is below requirement ({min_score})",
                            )

            user_langs = [
                lang.name.lower() for lang in user_profile.languages if lang.name
            ]
            if not user_langs and not user_profile.test_results:
                return (
                    RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                    "Language test required but user language test scores are missing from profile (neutral)",
                )

        return (
            RequirementMatchDecision.NEUTRAL_UNKNOWN,
            "Language requirement cannot be determined from available profile data",
        )

    def _eval_experience(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if req.value == "no_experience_required":
            return (
                RequirementMatchDecision.MATCHED,
                "Experience explicitly not required",
            )

        if not user_profile.experiences:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "PREFERRED experience specified, but user profile experiences list is empty/missing (neutral, omitted from denominator)",
            )

        val = req.value
        req_area = "relevant_experience"
        if isinstance(val, dict):
            req_area = str(val.get("area") or "relevant_experience")
        elif isinstance(val, str):
            req_area = val

        if _user_has_matching_experience_area(user_profile, req_area):
            return (
                RequirementMatchDecision.MATCHED,
                f"User experiences match preferred experience area '{req_area}'",
            )

        return (
            RequirementMatchDecision.NOT_MATCHED,
            f"User experiences {user_profile.experiences[:3]} do not match preferred experience area '{req_area}'",
        )

    def _eval_financial_need(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if user_profile.has_financial_need is None:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "Financial need requirement present but user has_financial_need is missing (neutral)",
            )
        if user_profile.has_financial_need:
            return (
                RequirementMatchDecision.MATCHED,
                "User has_financial_need=True matches requirement",
            )
        return (
            RequirementMatchDecision.NOT_MATCHED,
            "User has_financial_need=False does not match requirement",
        )

    def _eval_field_of_study(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if req.value == "open_to_all":
            return (
                RequirementMatchDecision.MATCHED,
                "Field of study open to all (matched)",
            )
        user_fields = [f.name.lower() for f in user_profile.fields_of_study if f.name]
        user_majors = [e.major.lower() for e in user_profile.educations if e.major]
        all_user_disciplines = user_fields + user_majors

        if not all_user_disciplines:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "Field of study required but user fields_of_study/majors are missing from profile (neutral)",
            )

        req_fields = req.value if isinstance(req.value, list) else [str(req.value)]
        for rfield in req_fields:
            rf_lower = str(rfield).lower()
            for udisc in all_user_disciplines:
                if rf_lower == udisc:
                    return (
                        RequirementMatchDecision.MATCHED,
                        f"User field/major '{udisc}' exactly matches required field '{rfield}'",
                    )

        return (
            RequirementMatchDecision.NOT_MATCHED,
            f"User fields {all_user_disciplines[:3]} do not match required fields {req_fields[:3]}",
        )

    def _eval_nationality(
        self,
        user_profile: UserProfileDTO,
        req: ExtractedRequirement,
    ) -> tuple[RequirementMatchDecision, str]:
        if user_profile.nationality is None:
            return (
                RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA,
                "Nationality requirement present but user nationality is missing (neutral)",
            )
        norm_user = (
            self._norm.normalize_country(user_profile.nationality)
            or user_profile.nationality
        )
        req_nats = req.value if isinstance(req.value, list) else [str(req.value)]
        norm_reqs = [(self._norm.normalize_country(c) or c).lower() for c in req_nats]

        if norm_user.lower() in norm_reqs:
            return (
                RequirementMatchDecision.MATCHED,
                f"User nationality '{user_profile.nationality}' matches requirement {req_nats[:3]}",
            )
        return (
            RequirementMatchDecision.NOT_MATCHED,
            f"User nationality '{user_profile.nationality}' does not match requirement {req_nats[:3]}",
        )
