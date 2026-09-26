"""Category evaluators implementing Safe V1 scoring rules for Afaq AI Matching Engine."""

from typing import Any

from src.modules.matching.models import (
    MATCH_SCORE_WEIGHTS,
    CategoryScoreDTO,
    ExtractedRequirement,
    RequirementStatus,
)
from src.modules.matching.services.requirement_extractor import (
    NON_ACADEMIC_FIELD_TOKENS,
)
from src.modules.scraping.services.normalization_service import NormalizationService

CEFR_LEVEL_RANKS: dict[str, int] = {
    "a1": 1,
    "beginner": 1,
    "elementary": 1,
    "مبتدئ": 1,
    "a2": 2,
    "pre-intermediate": 2,
    "b1": 3,
    "intermediate": 3,
    "متوسط": 3,
    "b2": 4,
    "upper-intermediate": 4,
    "جيد جدا": 4,
    "c1": 5,
    "advanced": 5,
    "fluent": 5,
    "proficient": 5,
    "متقن": 5,
    "ممتاز": 5,
    "c2": 6,
    "mastery": 6,
    "native": 6,
    "bilingual": 6,
    "mother tongue": 6,
    "اللغة الأم": 6,
}

OPEN_AND_NOISE_FIELD_TOKENS: set[str] = NON_ACADEMIC_FIELD_TOKENS | {
    "all",
    "all fields",
    "all subjects",
    "all disciplines",
    "any",
    "general",
    "open to all",
    "جميع التخصصات",
    "كافة التخصصات",
    "مفتوح للجميع",
}


def _get_user_disciplines(user_profile: Any) -> list[str]:
    """Extracts all user fields of study and education majors."""
    disciplines: list[str] = []
    if isinstance(user_profile, dict):
        for f in user_profile.get("fields_of_study") or []:
            name = f.get("name") if isinstance(f, dict) else str(f)
            if name and str(name).strip():
                disciplines.append(str(name).strip())
        for e in user_profile.get("educations") or []:
            major = e.get("major") if isinstance(e, dict) else getattr(e, "major", None)
            if major and str(major).strip():
                disciplines.append(str(major).strip())
    else:
        for f in getattr(user_profile, "fields_of_study", None) or []:
            name = getattr(f, "name", None) if not isinstance(f, str) else f
            if name and str(name).strip():
                disciplines.append(str(name).strip())
        for e in getattr(user_profile, "educations", None) or []:
            major = getattr(e, "major", None) if not isinstance(e, str) else e
            if major and str(major).strip():
                disciplines.append(str(major).strip())
    return disciplines


def _get_user_skills(user_profile: Any) -> list[str]:
    """Extracts all user skill names."""
    skills: list[str] = []
    if isinstance(user_profile, dict):
        for s in user_profile.get("skills") or []:
            name = s.get("name") if isinstance(s, dict) else str(s)
            if name and str(name).strip():
                skills.append(str(name).strip())
    else:
        for s in getattr(user_profile, "skills", None) or []:
            name = getattr(s, "name", None) if not isinstance(s, str) else s
            if name and str(name).strip():
                skills.append(str(name).strip())
    return skills


def _get_user_highest_gpa(user_profile: Any) -> float | None:
    """Extracts the highest normalized 4.0 GPA from user education records."""
    gpas: list[float] = []
    if isinstance(user_profile, dict):
        for e in user_profile.get("educations") or []:
            gpa = (
                e.get("gpa_normalized_4")
                if isinstance(e, dict)
                else getattr(e, "gpa_normalized_4", None)
            )
            if gpa is not None:
                try:
                    gpas.append(float(gpa))
                except (ValueError, TypeError):
                    pass
    else:
        for e in getattr(user_profile, "educations", None) or []:
            gpa = getattr(e, "gpa_normalized_4", None)
            if gpa is not None:
                try:
                    gpas.append(float(gpa))
                except (ValueError, TypeError):
                    pass
    return max(gpas) if gpas else None


def _get_user_languages(user_profile: Any) -> list[dict[str, Any]]:
    """Extracts all user languages and their proficiencies."""
    langs: list[dict[str, Any]] = []
    if isinstance(user_profile, dict):
        for l_item in user_profile.get("languages") or []:
            if isinstance(l_item, dict):
                langs.append(
                    {
                        "name": l_item.get("name"),
                        "proficiency": l_item.get("proficiency"),
                    }
                )
            else:
                langs.append({"name": str(l_item), "proficiency": None})
    else:
        for l_item in getattr(user_profile, "languages", None) or []:
            if isinstance(l_item, dict):
                langs.append(
                    {
                        "name": l_item.get("name"),
                        "proficiency": l_item.get("proficiency"),
                    }
                )
            else:
                name = getattr(l_item, "name", None) or str(l_item)
                prof = getattr(l_item, "proficiency", None)
                langs.append({"name": name, "proficiency": prof})
    return langs


# ============================================================================
# 1. FIELD OF STUDY EVALUATOR (30% weight)
# ============================================================================


def evaluate_field_of_study(
    user_profile: Any,
    req: ExtractedRequirement | None,
    normalizer: NormalizationService | None = None,
) -> CategoryScoreDTO:
    """Evaluates Field of Study (30% weight) under Safe V1 rules."""
    category = "field_of_study"
    weight = MATCH_SCORE_WEIGHTS[category]

    if req is None or req.status == RequirementStatus.UNKNOWN:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=RequirementStatus.UNKNOWN if req is None else req.status,
            reason="No explicit field of study requirement found in opportunity (silent)",
            extracted_requirement=req,
            user_data_used=None,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no field of study restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    val = req.value or {}
    req_fields: list[str] = []
    if isinstance(val, dict) and "fields" in val:
        req_fields = [str(f).strip() for f in val["fields"] if str(f).strip()]
    elif isinstance(val, list):
        req_fields = [str(f).strip() for f in val if str(f).strip()]

    if not req_fields:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=req.status,
            reason="Field of study requirement list is empty or uncomputable",
            extracted_requirement=req,
            user_data_used=None,
        )

    # Filter out non-academic general tokens (e.g. 'all', 'all fields', 'general')
    academic_req_fields = [
        f for f in req_fields if f.lower() not in OPEN_AND_NOISE_FIELD_TOKENS
    ]
    if not academic_req_fields:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="All fields of study eligible (open/general), category is neutral",
            extracted_requirement=req,
            user_data_used=None,
        )

    user_disciplines = _get_user_disciplines(user_profile)
    if not user_disciplines:
        if req.status == RequirementStatus.REQUIRED:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason="Opportunity requires specific fields of study, but user field/major is missing from profile",
                extracted_requirement=req,
                user_data_used=None,
            )
        else:  # PREFERRED
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=False,
                status=req.status,
                reason="Preferred fields of study not provided in user profile (neutral, no penalty)",
                extracted_requirement=req,
                user_data_used=None,
            )

    # Check exact match
    req_lower_set = {f.lower() for f in academic_req_fields}
    matched_discipline = None
    for u in user_disciplines:
        if u.lower() in req_lower_set:
            matched_discipline = u
            break

    if matched_discipline:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=100.0,
            weighted_score=weight,
            is_computable=True,
            is_applicable=True,
            status=req.status,
            reason=f"User field of study '{matched_discipline}' exactly matches required fields: {academic_req_fields}",
            extracted_requirement=req,
            user_data_used=user_disciplines,
        )

    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score_pct=0.0,
        weighted_score=0.0,
        is_computable=True,
        is_applicable=True,
        status=req.status,
        reason=f"User fields of study {user_disciplines} do not match required fields: {academic_req_fields}",
        extracted_requirement=req,
        user_data_used=user_disciplines,
    )


# ============================================================================
# 2. SKILLS / INTERESTS EVALUATOR (25% weight)
# ============================================================================


def evaluate_skills(
    user_profile: Any,
    req: ExtractedRequirement | None,
    normalizer: NormalizationService | None = None,
) -> CategoryScoreDTO:
    """Evaluates Skills / Interests (25% weight) under Safe V1 rules."""
    category = "skills"
    weight = MATCH_SCORE_WEIGHTS[category]

    if req is None or req.status == RequirementStatus.UNKNOWN:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=RequirementStatus.UNKNOWN if req is None else req.status,
            reason="No explicit applicant skill requirement found in opportunity (silent)",
            extracted_requirement=req,
            user_data_used=None,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no applicant skill restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    val = req.value or {}
    req_skills: list[str] = []
    if isinstance(val, dict):
        if "skills" in val and isinstance(val["skills"], list):
            req_skills = [str(s).strip() for s in val["skills"] if str(s).strip()]
        elif "skill" in val and val["skill"]:
            req_skills = [str(val["skill"]).strip()]
    elif isinstance(val, list):
        req_skills = [str(s).strip() for s in val if str(s).strip()]

    if not req_skills:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=req.status,
            reason="Applicant skill requirement list is empty or uncomputable",
            extracted_requirement=req,
            user_data_used=None,
        )

    user_skills = _get_user_skills(user_profile)
    if not user_skills:
        if req.status == RequirementStatus.REQUIRED:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason="Opportunity requires specific applicant skills, but user skills are missing from profile",
                extracted_requirement=req,
                user_data_used=None,
            )
        else:  # PREFERRED
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=False,
                status=req.status,
                reason="Optional/preferred skills not provided in user profile (neutral, no penalty)",
                extracted_requirement=req,
                user_data_used=None,
            )

    user_skills_set = {s.lower() for s in user_skills}
    req_skills_set = {s.lower() for s in req_skills}

    matched_skills = user_skills_set & req_skills_set
    score = (len(matched_skills) / len(req_skills_set)) * 100.0
    score_pct = round(score, 2)
    weighted = (score_pct / 100.0) * weight

    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score_pct=score_pct,
        weighted_score=round(weighted, 4),
        is_computable=True,
        is_applicable=True,
        status=req.status,
        reason=f"User has {len(matched_skills)} of {len(req_skills_set)} required skills ({list(matched_skills)})",
        extracted_requirement=req,
        user_data_used=user_skills,
    )


# ============================================================================
# 3. GPA / ACADEMIC STANDING EVALUATOR (20% weight)
# ============================================================================


def evaluate_gpa(
    user_profile: Any,
    req: ExtractedRequirement | None,
    normalizer: NormalizationService | None = None,
) -> CategoryScoreDTO:
    """Evaluates GPA / Academic Standing (20% weight) under Safe V1 rules."""
    category = "gpa"
    weight = MATCH_SCORE_WEIGHTS[category]

    if req is None or req.status == RequirementStatus.UNKNOWN:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=RequirementStatus.UNKNOWN if req is None else req.status,
            reason="No explicit GPA requirement found in opportunity (silent)",
            extracted_requirement=req,
            user_data_used=None,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no GPA restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    val = req.value or {}
    t_threshold: float | None = None

    if isinstance(val, dict):
        gpa_type = str(val.get("type", "")).upper()
        if (
            gpa_type in ("QUALITATIVE", "HONORS")
            or "text" in val
            or "description" in val
        ):
            desc = val.get("description") or val.get("honors") or val.get("text")
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=False,
                is_applicable=False,
                status=req.status,
                reason=f"Qualitative GPA requirement '{desc}' cannot be safely computed in V1 without approved conversion taxonomy",
                extracted_requirement=req,
                user_data_used=None,
            )

        if "min_gpa_normalized_4" in val and val["min_gpa_normalized_4"] is not None:
            try:
                t_threshold = float(val["min_gpa_normalized_4"])
            except (ValueError, TypeError):
                pass
        elif "minimum" in val and val["minimum"] is not None:
            try:
                raw_val = float(val["minimum"])
                scale = float(val.get("scale", 4.0)) or 4.0
                t_threshold = (raw_val / scale) * 4.0 if scale != 4.0 else raw_val
            except (ValueError, TypeError):
                pass
        elif "min_gpa" in val and val["min_gpa"] is not None:
            try:
                t_threshold = float(val["min_gpa"])
            except (ValueError, TypeError):
                pass

    if t_threshold is None:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=req.status,
            reason="Qualitative GPA requirement cannot be safely computed in V1 without approved conversion taxonomy",
            extracted_requirement=req,
            user_data_used=None,
        )

    user_gpa = _get_user_highest_gpa(user_profile)
    if user_gpa is None:
        if req.status == RequirementStatus.REQUIRED:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"Opportunity requires minimum GPA of {t_threshold:.2f}, but user GPA is missing from profile",
                extracted_requirement=req,
                user_data_used=None,
            )
        else:  # PREFERRED
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=False,
                status=req.status,
                reason=f"Preferred GPA of {t_threshold:.2f} not provided in user profile (neutral, no penalty)",
                extracted_requirement=req,
                user_data_used=None,
            )

    if user_gpa >= t_threshold:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=100.0,
            weighted_score=weight,
            is_computable=True,
            is_applicable=True,
            status=req.status,
            reason=f"User GPA ({user_gpa:.2f}) meets or exceeds required GPA threshold ({t_threshold:.2f})",
            extracted_requirement=req,
            user_data_used=user_gpa,
        )

    # User GPA is below threshold -> 0.0% in category (No below-threshold curve)
    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score_pct=0.0,
        weighted_score=0.0,
        is_computable=True,
        is_applicable=True,
        status=req.status,
        reason=f"User GPA ({user_gpa:.2f}) is below required GPA threshold ({t_threshold:.2f})",
        extracted_requirement=req,
        user_data_used=user_gpa,
    )


# ============================================================================
# 4. LANGUAGE PROFICIENCY EVALUATOR (15% weight)
# ============================================================================


def evaluate_language(
    user_profile: Any,
    req: ExtractedRequirement | None,
    normalizer: NormalizationService | None = None,
) -> CategoryScoreDTO:
    """Evaluates Language Proficiency (15% weight) under Safe V1 rules."""
    category = "language"
    weight = MATCH_SCORE_WEIGHTS[category]

    if req is None or req.status == RequirementStatus.UNKNOWN:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=RequirementStatus.UNKNOWN if req is None else req.status,
            reason="No explicit language requirement found in opportunity (silent)",
            extracted_requirement=req,
            user_data_used=None,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no language certificate restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    val = req.value or {}
    if isinstance(val, dict) and val.get("no_certificate_required") is True:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no language certificate restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    # Determine required language and min rank
    required_lang = "english"
    min_rank = 4  # Default B2 / IELTS 6.5 / TOEFL 80

    if isinstance(val, dict):
        if (
            "languages" in val
            and isinstance(val["languages"], list)
            and val["languages"]
        ):
            first_lang_spec = val["languages"][0]
            if isinstance(first_lang_spec, dict):
                required_lang = (
                    str(first_lang_spec.get("name") or "english").strip().lower()
                )
                min_prof_str = (
                    str(first_lang_spec.get("min_proficiency") or "b2").strip().lower()
                )
                min_rank = CEFR_LEVEL_RANKS.get(min_prof_str, 4)
            else:
                required_lang = str(first_lang_spec).strip().lower()
        elif "language" in val and val["language"]:
            required_lang = str(val["language"]).strip().lower()
        elif "tests" in val and isinstance(val["tests"], list) and val["tests"]:
            first_test = val["tests"][0]
            if isinstance(first_test, dict):
                required_lang = (
                    str(first_test.get("language") or "english").strip().lower()
                )
                min_score = first_test.get("min_score")
                if min_score is not None:
                    try:
                        if float(min_score) >= 7.0:
                            min_rank = 5  # C1
                        else:
                            min_rank = 4  # B2
                    except (ValueError, TypeError):
                        min_rank = 4

    user_languages = _get_user_languages(user_profile)
    if not user_languages:
        if req.status == RequirementStatus.REQUIRED:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"Opportunity requires proficiency in {required_lang.capitalize()}, but user languages are missing from profile",
                extracted_requirement=req,
                user_data_used=None,
            )
        else:  # PREFERRED
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=False,
                status=req.status,
                reason=f"Preferred language proficiency in {required_lang.capitalize()} not provided in user profile (neutral, no penalty)",
                extracted_requirement=req,
                user_data_used=None,
            )

    # Check user proficiency in target language
    target_entries = [
        lang_entry
        for lang_entry in user_languages
        if lang_entry.get("name")
        and str(lang_entry["name"]).strip().lower() == required_lang
    ]

    if not target_entries:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=0.0,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=True,
            status=req.status,
            reason=f"User profile does not include required language '{required_lang.capitalize()}'",
            extracted_requirement=req,
            user_data_used=user_languages,
        )

    user_prof_raw = str(target_entries[0].get("proficiency") or "").strip().lower()
    user_rank = CEFR_LEVEL_RANKS.get(user_prof_raw)

    if user_rank is not None:
        if user_rank >= min_rank:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=100.0,
                weighted_score=weight,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"User proficiency '{user_prof_raw}' meets or exceeds required proficiency for '{required_lang.capitalize()}'",
                extracted_requirement=req,
                user_data_used=target_entries,
            )
        else:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"User proficiency '{user_prof_raw}' is below required proficiency for '{required_lang.capitalize()}'",
                extracted_requirement=req,
                user_data_used=target_entries,
            )

    # Unrecognized proficiency scale
    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score_pct=None,
        weighted_score=0.0,
        is_computable=False,
        is_applicable=False,
        status=req.status,
        reason=f"User proficiency '{user_prof_raw}' for '{required_lang.capitalize()}' cannot be safely converted in V1 without approved equivalency table",
        extracted_requirement=req,
        user_data_used=target_entries,
    )


# ============================================================================
# 5. EXPERIENCE EVALUATOR (10% weight)
# ============================================================================


def evaluate_experience(
    user_profile: Any,
    req: ExtractedRequirement | None,
    normalizer: NormalizationService | None = None,
) -> CategoryScoreDTO:
    """Evaluates Work / Research Experience (10% weight) under Safe V1 rules."""
    category = "experience"
    weight = MATCH_SCORE_WEIGHTS[category]

    if req is None or req.status == RequirementStatus.UNKNOWN:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=RequirementStatus.UNKNOWN if req is None else req.status,
            reason="No explicit experience requirement found in opportunity (silent)",
            extracted_requirement=req,
            user_data_used=None,
        )

    if req.status == RequirementStatus.NOT_REQUIRED:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=True,
            is_applicable=False,
            status=RequirementStatus.NOT_REQUIRED,
            reason="Opportunity explicitly has no experience restrictions (neutral/waived)",
            extracted_requirement=req,
            user_data_used=None,
        )

    val = req.value or {}
    min_years: float | None = None

    if isinstance(val, dict):
        if "min_years" in val and val["min_years"] is not None:
            try:
                min_years = float(val["min_years"])
            except (ValueError, TypeError):
                pass
        elif "minimum_years" in val and val["minimum_years"] is not None:
            try:
                min_years = float(val["minimum_years"])
            except (ValueError, TypeError):
                pass
        elif "years" in val and val["years"] is not None:
            try:
                min_years = float(val["years"])
            except (ValueError, TypeError):
                pass

    if min_years is None:
        return CategoryScoreDTO(
            category=category,
            weight=weight,
            score_pct=None,
            weighted_score=0.0,
            is_computable=False,
            is_applicable=False,
            status=req.status,
            reason="Qualitative experience requirement cannot be safely computed in V1 without approved level-to-years mapping",
            extracted_requirement=req,
            user_data_used=None,
        )

    user_exp_level = (
        user_profile.get("experience_level")
        if isinstance(user_profile, dict)
        else getattr(user_profile, "experience_level", None)
    )

    if not user_exp_level:
        if req.status == RequirementStatus.REQUIRED:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"Opportunity requires {min_years} years of experience, but user experience is missing from profile",
                extracted_requirement=req,
                user_data_used=None,
            )
        else:  # PREFERRED
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=None,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=False,
                status=req.status,
                reason=f"Preferred experience of {min_years} years not provided in user profile (neutral, no penalty)",
                extracted_requirement=req,
                user_data_used=None,
            )

    # Check if user experience level can be parsed as numeric years
    user_numeric_years: float | None = None
    try:
        user_numeric_years = float(str(user_exp_level).strip())
    except (ValueError, TypeError):
        pass

    if user_numeric_years is not None:
        if user_numeric_years >= min_years:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=100.0,
                weighted_score=weight,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"User experience ({user_numeric_years} years) meets or exceeds required {min_years} years",
                extracted_requirement=req,
                user_data_used=user_exp_level,
            )
        else:
            return CategoryScoreDTO(
                category=category,
                weight=weight,
                score_pct=0.0,
                weighted_score=0.0,
                is_computable=True,
                is_applicable=True,
                status=req.status,
                reason=f"User experience ({user_numeric_years} years) is below required {min_years} years",
                extracted_requirement=req,
                user_data_used=user_exp_level,
            )

    # Qualitative level string like 'mid', 'senior' -> Uncomputable without approved mapping
    return CategoryScoreDTO(
        category=category,
        weight=weight,
        score_pct=None,
        weighted_score=0.0,
        is_computable=False,
        is_applicable=False,
        status=req.status,
        reason=f"User experience level '{user_exp_level}' cannot be safely converted to numeric years in V1 without approved mapping",
        extracted_requirement=req,
        user_data_used=user_exp_level,
    )
