import logging
import re
from typing import Any

from src.modules.matching.models import (
    OPEN_TO_ALL_NATIONALITIES,
    ConfidenceLevel,
    ExtractedRequirement,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementScope,
    RequirementStatus,
    RequirementType,
)
from src.modules.scraping.services.normalization_service import (
    COUNTRY_MAPPINGS,
    NormalizationService,
)

logger = logging.getLogger(__name__)

# Non-academic noise tokens in fields_of_study scraper tags
NON_ACADEMIC_FIELD_TOKENS = {
    # Geographic tokens
    "germany",
    "deutschland",
    "europe",
    "usa",
    "united states",
    "united states of america",
    "uk",
    "united kingdom",
    "great britain",
    "canada",
    "australia",
    "asia",
    "asian",
    "middle east",
    "qatar",
    "france",
    "turkey",
    "türkiye",
    "turkiye",
    "switzerland",
    "netherlands",
    "holland",
    "sweden",
    "japan",
    "china",
    "ireland",
    "new zealand",
    "singapore",
    "belgium",
    "saudi arabia",
    "uae",
    "united arab emirates",
    "egypt",
    "south korea",
    "korea",
    "italy",
    "spain",
    "austria",
    "norway",
    "finland",
    "denmark",
    # Scraper metadata tokens
    "scholarships",
    "scholarship",
    "masters scholarships",
    "master scholarships",
    "ph.d scholarships",
    "phd scholarships",
    "undergraduate scholarships",
    "bachelor scholarships",
    "postgraduate scholarships",
    "international scholarships",
    "women scholarships",
    "fellowships",
    "fellowship",
    "internships",
    "internship",
    "study abroad",
    "study in europe",
    "study in canada",
    "study in uk",
    "study in germany",
    "study in china",
    "study in japan",
    "study in usa",
    "study in australia",
    "fully funded",
    "partially funded",
    "funded",
    "online",
    "exchange",
}


# Nationality regex helpers
_FOLLOWING_NATIONALITY_RESTRICTION_PATTERN = re.compile(
    r"^(?:\s+from|\s+who\s+are|\s+of)\s+("
    r"developing\s+countr"
    r"|eligible\s+countr"
    r"|selected\s+countr"
    r"|participating\s+countr"
    r"|partner\s+countr"
    r"|oecd[- ]dac"
    r"|dac\s+list"
    r"|non[- ]eu"
    r"|outside\s+the\s+eu"
    r"|africa"
    r"|asia"
    r"|latin\s+america"
    r"|commonwealth"
    r"|[A-Z][a-z]+(?:\s*,\s*[A-Z][a-z]+)+"
    r")",
    re.IGNORECASE,
)

_TARGET_GROUP_PATTERN = re.compile(r"(?i)\btarget\s+group\s*:\s*([^\n\r]+)")

_TARGET_GROUP_OPEN_PATTERN = re.compile(
    r"(?i)^\s*("
    r"all\s+applicants(?:\s+from\s+any\s+country)?"
    r"|all\s+students(?:\s+including\s+international\s+students)?"
    r"|national\s+and\s+international\s+students"
    r"|international\s+and\s+eu\s+students"
    r"|international\s+students\s*$"
    r")\s*$"
)

_TARGET_GROUP_RESTRICTED_PATTERN = re.compile(
    r"(?i)\b("
    r"non[- ]eu(?:/eea(?:/efta)?)?"
    r"|outside\s+the\s+eu(?:/eea)?"
    r"|citizens?\s+from\s+non[- ]eu"
    r"|women\s+who\s+are\s+not\s+(?:united\s+states|u\.?s\.?)\s+citizens"
    r"|developing\s+countr(?:ies|y)"
    r"|eligible\s+countries"
    r"|dac\s+list"
    r"|oecd[- ]dac"
    r"|africa"
    r"|commonwealth"
    r")\b"
)

_TARGET_GROUP_DEFER_PATTERN = re.compile(
    r"(?i)\b(?:from\s+(?:more\s+than\s+)?\d+\s+countries)\b"
)

_NEGATION_PREFIX_PATTERN = re.compile(
    r"(?i)\b(?:not|non[- ]|are\s+not|aren't|excluding|except|other\s+than|neither|never|not\s+eligible\s+if(?:\s+you\s+are)?)\s*$"
)


def _clean_span(text: str, start: int, end: int, max_len: int = 160) -> str:
    """Extracts and cleans a readable snippet surrounding matched positions."""
    s = max(0, start - 20)
    e = min(len(text), end + 40)
    snippet = text[s:e].replace("\n", " ").strip()
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
    return snippet


class RequirementExtractor:
    """Analyzes a cleaned opportunity and extracts explicit applicant requirements.

    Adheres strictly to the principle:
    - Explicit evidence only (REQUIRED, PREFERRED, NOT_REQUIRED).
    - Silence is NOT evidence of absence (remains UNKNOWN).
    - Never converts missing opportunity data into N/A.
    """

    def __init__(
        self, normalization_service: NormalizationService | None = None
    ) -> None:
        self.normalizer = normalization_service or NormalizationService()

    def extract_requirements(self, opportunity: Any) -> OpportunityRequirementsDTO:
        """Extracts all explicit requirements from an opportunity record."""
        opp_id = getattr(opportunity, "id", None) or (
            opportunity.get("id") if isinstance(opportunity, dict) else None
        )
        requirements: list[ExtractedRequirement] = []

        # Gather structured fields and text
        if isinstance(opportunity, dict):
            title = str(opportunity.get("title") or "")
            description = str(opportunity.get("description") or "")
            eligibility_raw = opportunity.get("eligibility") or {}
            study_levels = opportunity.get("study_levels") or []
            fields_of_study = opportunity.get("fields_of_study") or []
            opportunity_type = str(opportunity.get("opportunity_type") or "")
            deadline = opportunity.get("deadline")
        else:
            title = str(getattr(opportunity, "title", None) or "")
            description = str(getattr(opportunity, "description", None) or "")
            eligibility_raw = getattr(opportunity, "eligibility", None) or {}
            study_levels = getattr(opportunity, "study_levels", None) or []
            fields_of_study = getattr(opportunity, "fields_of_study", None) or []
            opportunity_type = str(getattr(opportunity, "opportunity_type", None) or "")
            deadline = getattr(opportunity, "deadline", None)

        eligibility_text = (
            eligibility_raw.get("eligibility_text", "")
            if isinstance(eligibility_raw, dict)
            else ""
        )
        eligible_nationalities = (
            eligibility_raw.get("eligible_nationalities")
            if isinstance(eligibility_raw, dict)
            else None
        )

        full_text = f"{title}\n{eligibility_text}\n{description}"

        # 1. Nationality & Residency
        requirements.extend(
            self._extract_nationality(eligible_nationalities, full_text)
        )
        requirements.extend(self._extract_residency(full_text))

        # 2. Education Level
        requirements.extend(self._extract_education(study_levels, full_text, title))

        # 3. Field of Study
        requirements.extend(self._extract_field_of_study(fields_of_study, full_text))

        # 4. GPA & Academic Performance
        requirements.extend(self._extract_gpa(eligibility_text, description))

        # 5. Language Requirements
        requirements.extend(self._extract_language(full_text))

        # 6. Experience (Work / Research)
        requirements.extend(self._extract_experience(full_text, opportunity_type))

        # 7. Age
        requirements.extend(self._extract_age(full_text))

        # 8. Skills & Interests
        requirements.extend(self._extract_skills(eligibility_text, description))

        # 9. Gender & Financial Need
        requirements.extend(self._extract_gender(full_text))
        requirements.extend(self._extract_financial_need(full_text))

        # 10. Application Requirements
        requirements.extend(self._extract_application_documents(full_text))

        # 11. Lifecycle (Deadline)
        if deadline:
            requirements.append(
                ExtractedRequirement(
                    category="deadline",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.LIFECYCLE,
                    scope=RequirementScope.APPLICATION,
                    value={"deadline": str(deadline)},
                    evidence=f"Application deadline: {deadline}",
                    confidence=ConfidenceLevel.HIGH,
                    source_field="deadline",
                )
            )

        return OpportunityRequirementsDTO(
            opportunity_id=opp_id, requirements=requirements
        )

    # ========================================================================
    # 1. Nationality & Residency Extractors
    # ========================================================================

    def _extract_nationality(
        self, eligible_nationalities: Any, full_text: str
    ) -> list[ExtractedRequirement]:
        """Extracts nationality requirements without inferring from country of study."""
        reqs: list[ExtractedRequirement] = []

        # Check structured eligible_nationalities first
        if eligible_nationalities is not None:
            if isinstance(eligible_nationalities, str):
                raw_items = [eligible_nationalities.strip()]
            elif isinstance(eligible_nationalities, list):
                raw_items = [
                    str(x).strip() for x in eligible_nationalities if str(x).strip()
                ]
            else:
                raw_items = []

            if raw_items:
                # Check if canonical open-to-all
                is_open = any(
                    item.lower() in OPEN_TO_ALL_NATIONALITIES for item in raw_items
                )
                if is_open:
                    reqs.append(
                        ExtractedRequirement(
                            category="nationality",
                            status=RequirementStatus.NOT_REQUIRED,
                            requirement_type=RequirementType.ELIGIBILITY,
                            scope=RequirementScope.SCHOLARSHIP,
                            value={"open_to_all": True},
                            evidence=f"eligible_nationalities: {raw_items}",
                            confidence=ConfidenceLevel.HIGH,
                            source_field="eligibility.eligible_nationalities",
                        )
                    )
                    return reqs
                else:
                    reqs.append(
                        ExtractedRequirement(
                            category="nationality",
                            status=RequirementStatus.REQUIRED,
                            requirement_type=RequirementType.ELIGIBILITY,
                            scope=RequirementScope.SCHOLARSHIP,
                            value={"countries": raw_items},
                            operator="IN",
                            evidence=f"eligible_nationalities: {raw_items}",
                            confidence=ConfidenceLevel.HIGH,
                            source_field="eligibility.eligible_nationalities",
                        )
                    )
                    return reqs

        # 2. Check Target group section if present
        tg_match = _TARGET_GROUP_PATTERN.search(full_text)
        if tg_match:
            tg_text = tg_match.group(1).strip()
            tg_lower = tg_text.lower()

            # Check if deferred (external count like "from 155 countries" or "from more than 180 countries")
            if _TARGET_GROUP_DEFER_PATTERN.search(tg_text):
                pass
            # Check exclusion in target group (e.g. AU Emerging vs AAUW)
            elif (
                "who are not" in tg_lower
                or "not u.s." in tg_lower
                or "not united states" in tg_lower
            ):
                if "women who are not" in tg_lower:
                    # AAUW explicit restriction for non-US women
                    reqs.append(
                        ExtractedRequirement(
                            category="nationality",
                            status=RequirementStatus.REQUIRED,
                            requirement_type=RequirementType.ELIGIBILITY,
                            scope=RequirementScope.SCHOLARSHIP,
                            value={"description": tg_text[:100]},
                            operator="IN",
                            evidence=_clean_span(
                                full_text, tg_match.start(), tg_match.end()
                            ),
                            confidence=ConfidenceLevel.HIGH,
                            source_field="eligibility_text",
                        )
                    )
                    return reqs
                else:
                    # AU Emerging exclusion -> cannot convert exclusion to positive requirement
                    reqs.append(
                        ExtractedRequirement(
                            category="nationality",
                            status=RequirementStatus.UNKNOWN,
                            requirement_type=RequirementType.ELIGIBILITY,
                            scope=RequirementScope.SCHOLARSHIP,
                            evidence=_clean_span(
                                full_text, tg_match.start(), tg_match.end()
                            ),
                            confidence=ConfidenceLevel.LOW,
                            source_field="eligibility_text",
                        )
                    )
                    return reqs
            # Check if unrestricted open target group
            elif _TARGET_GROUP_OPEN_PATTERN.match(tg_text):
                reqs.append(
                    ExtractedRequirement(
                        category="nationality",
                        status=RequirementStatus.NOT_REQUIRED,
                        requirement_type=RequirementType.ELIGIBILITY,
                        scope=RequirementScope.SCHOLARSHIP,
                        value={"open_to_all": True},
                        evidence=_clean_span(
                            full_text, tg_match.start(), tg_match.end()
                        ),
                        confidence=ConfidenceLevel.HIGH,
                        source_field="eligibility_text",
                    )
                )
                return reqs
            # Check if restricted target group
            elif _TARGET_GROUP_RESTRICTED_PATTERN.search(tg_text):
                reqs.append(
                    ExtractedRequirement(
                        category="nationality",
                        status=RequirementStatus.REQUIRED,
                        requirement_type=RequirementType.ELIGIBILITY,
                        scope=RequirementScope.SCHOLARSHIP,
                        value={"description": tg_text[:100]},
                        operator="IN",
                        evidence=_clean_span(
                            full_text, tg_match.start(), tg_match.end()
                        ),
                        confidence=ConfidenceLevel.HIGH,
                        source_field="eligibility_text",
                    )
                )
                return reqs
            elif (
                ("," in tg_text or "•" in tg_text or ":" in tg_text)
                and len(tg_text) > 30
                and not tg_lower.startswith("all enrolled")
                and not tg_lower.startswith("the scholarships are targeted")
            ):
                # Country list in Target group e.g. "Australia, Bermuda, Canada..." or "In Africa: Benin..." or "Afghanistan, Angola..."
                reqs.append(
                    ExtractedRequirement(
                        category="nationality",
                        status=RequirementStatus.REQUIRED,
                        requirement_type=RequirementType.ELIGIBILITY,
                        scope=RequirementScope.SCHOLARSHIP,
                        value={"description": tg_text[:100]},
                        operator="IN",
                        evidence=_clean_span(
                            full_text, tg_match.start(), tg_match.end()
                        ),
                        confidence=ConfidenceLevel.HIGH,
                        source_field="eligibility_text",
                    )
                )
                return reqs

        # 3. Text-based extraction fallback (Open)
        open_matches = list(
            re.finditer(
                r"(?i)\b(?:"
                r"open\s+(?:for|to)\s+(?:all\s+)?(?:international\s+students|all\s+nationalities|all\s+countries|students\s+worldwide)"
                r"|candidates\s+from\s+all\s+nations\s+eligible"
                r"|(?:students\s+from\s+)?all\s+nationalities"
                r"|all\s+countries\s+(?:of\s+the\s+world|are\s+eligible)"
                r"|be\s+of\s+any\s+nationality"
                r"|جميع\s+الجنسيات"
                r"|كافة\s+الجنسيات"
                r"|مفتوح\s+للجميع"
                r")\b",
                full_text,
            )
        )

        valid_open_match = None
        for m in open_matches:
            following_text = full_text[m.end() : m.end() + 60]
            if _FOLLOWING_NATIONALITY_RESTRICTION_PATTERN.search(following_text):
                continue
            valid_open_match = m
            break

        if valid_open_match:
            reqs.append(
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"open_to_all": True},
                    evidence=_clean_span(
                        full_text, valid_open_match.start(), valid_open_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # 4. Text-based extraction fallback (Restricted)
        restr_matches = list(
            re.finditer(
                r"(?i)\b(?:"
                r"citizens?\s+of\s+([A-Za-z\s,]+)"
                r"|nationals?\s+of\s+([A-Za-z\s,]+)"
                r"|national\s+of\s+a\s+country\s+listed\s+on\s+the\s+([A-Za-z\s,-]+)"
                r"|citizenship\s*&\s*residency\s*:\s*each\s+applicant\s+must\s+fulfil"
                r"|hold\s+the\s+nationality\s+of\s+a\s+country"
                r"|مواطني\s+([\u0600-\u06FF\s،]+)"
                r")\b",
                full_text,
            )
        )

        for m in restr_matches:
            preceding_text = full_text[max(0, m.start() - 35) : m.start()]
            if _NEGATION_PREFIX_PATTERN.search(preceding_text.strip()):
                continue

            matched_str = m.group(0).strip()
            if len(matched_str) > 80:
                matched_str = matched_str[:80].rsplit(" ", 1)[0]

            reqs.append(
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"description": matched_str},
                    operator="IN",
                    evidence=_clean_span(full_text, m.start(), m.end()),
                    confidence=ConfidenceLevel.MEDIUM,
                    source_field="description",
                )
            )
            return reqs

        # 5. Silent nationality -> UNKNOWN
        reqs.append(
            ExtractedRequirement(
                category="nationality",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.SCHOLARSHIP,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    def _extract_residency(self, full_text: str) -> list[ExtractedRequirement]:
        """Extracts residency requirements if explicitly present."""
        reqs: list[ExtractedRequirement] = []
        res_match = re.search(
            r"(?i)\b(?:must\s+be\s+residents?\s+of\s+([A-Za-z\s]+)|resident\s+and\s+national\s+of|المقيمين\s+في\s+([\u0600-\u06FF\s]+))\b",
            full_text,
        )
        if res_match:
            reqs.append(
                ExtractedRequirement(
                    category="residency",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"description": res_match.group(0).strip()},
                    evidence=_clean_span(full_text, res_match.start(), res_match.end()),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
        return reqs

    # ========================================================================
    # 2. Education Level Extractor
    # ========================================================================

    def _extract_education(
        self, study_levels: list[str], full_text: str, title: str
    ) -> list[ExtractedRequirement]:
        """Extracts study / degree level requirements."""
        reqs: list[ExtractedRequirement] = []

        if study_levels:
            norm_levels = self.normalizer.normalize_study_levels(study_levels)
            reqs.append(
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"degree_levels": norm_levels or study_levels},
                    operator="IN",
                    evidence=f"study_levels: {study_levels}",
                    confidence=ConfidenceLevel.HIGH,
                    source_field="study_levels",
                )
            )
            return reqs

        # Fallback regex in text
        edu_match = re.search(
            r"(?i)\b(?:bachelor'?s?|master'?s?|ph\.?d\.?|doctorate|undergraduate|postgraduate|بكالوريوس|ماجستير|دكتوراه)\b",
            f"{title}\n{full_text}",
        )
        if edu_match:
            detected_level = self.normalizer.normalize_study_levels(
                [edu_match.group(0)]
            )
            reqs.append(
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"degree_levels": detected_level or [edu_match.group(0)]},
                    operator="IN",
                    evidence=_clean_span(full_text, edu_match.start(), edu_match.end()),
                    confidence=ConfidenceLevel.MEDIUM,
                    source_field="description",
                )
            )
            return reqs

        reqs.append(
            ExtractedRequirement(
                category="education",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.ADMISSION,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="study_levels",
            )
        )
        return reqs

    # ========================================================================
    # 3. Field of Study Extractor
    # ========================================================================

    def _extract_field_of_study(
        self, fields_of_study: list[str], full_text: str
    ) -> list[ExtractedRequirement]:
        """Extracts academic disciplines while strictly rejecting geographic and metadata noise."""
        reqs: list[ExtractedRequirement] = []

        # 1. Check for explicit "Open to all fields"
        open_match = re.search(
            r"(?i)\b(?:open\s+to\s+all\s+(?:academic\s+)?(?:fields|disciplines|subjects|majors)|any\s+(?:eligible\s+)?(?:academic\s+)?(?:field|discipline|subject|course)|open\s+to\s+any\s+subject|all\s+academic\s+fields|جميع\s+التخصصات|كافة\s+التخصصات|مختلف\s+التخصصات)\b",
            full_text,
        )
        if open_match:
            reqs.append(
                ExtractedRequirement(
                    category="field_of_study",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.PROGRAM,
                    value={"open_to_all": True},
                    evidence=_clean_span(
                        full_text, open_match.start(), open_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # 2. Sanitize structured fields_of_study
        clean_disciplines = []
        for f in fields_of_study:
            f_clean = str(f).strip()
            f_lower = f_clean.lower()
            # Ignore noise tokens
            if f_lower in NON_ACADEMIC_FIELD_TOKENS:
                continue
            if any(country_key in f_lower for country_key in COUNTRY_MAPPINGS):
                continue
            if len(f_clean) < 3:
                continue
            clean_disciplines.append(f_clean)

        if clean_disciplines:
            reqs.append(
                ExtractedRequirement(
                    category="field_of_study",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.PROGRAM,
                    value={"fields": clean_disciplines},
                    operator="IN",
                    evidence=f"fields_of_study: {clean_disciplines}",
                    confidence=ConfidenceLevel.HIGH,
                    source_field="fields_of_study",
                )
            )
            return reqs

        # 3. Silent -> UNKNOWN
        reqs.append(
            ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.PROGRAM,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="fields_of_study",
            )
        )
        return reqs

    # ========================================================================
    # 4. GPA & Academic Performance Extractor
    # ========================================================================

    def _extract_gpa(
        self, eligibility_text: str, description: str
    ) -> list[ExtractedRequirement]:
        """Extracts GPA, percentage, honors standing, or qualitative academic requirements."""
        reqs: list[ExtractedRequirement] = []
        combined_text = f"{eligibility_text}\n{description}"

        # 1. Numeric GPA (e.g. minimum GPA of 3.5 / 4.0 or CGPA 3.0)
        gpa_num = re.search(
            r"(?i)\b(?:minimum\s+)?(?:c?gpa|agpa)\s+(?:of\s+|>=|:\s*)?([2-4](?:\.\d+)?)(?:\s*(?:/|\s+out\s+of\s+)(4(?:\.0)?))?\b",
            combined_text,
        )
        if gpa_num:
            val = float(gpa_num.group(1))
            scale = float(gpa_num.group(2)) if gpa_num.group(2) else 4.0
            reqs.append(
                ExtractedRequirement(
                    category="gpa",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"minimum": val, "scale": scale, "type": "NUMERIC"},
                    operator=">=",
                    evidence=_clean_span(combined_text, gpa_num.start(), gpa_num.end()),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # 2. Percentage threshold (e.g. 70% or 85%)
        pct_match = re.search(
            r"(?i)\b(?:minimum\s+)?(?:academic\s+)?(?:average|grade|نجاح|معدل)?\s*(?:of|لا\s+يقل\s+عن)?\s*([6-9]\d)%\s*(?:or\s+higher|على\s+الأقل)?\b",
            combined_text,
        )
        if pct_match:
            val = float(pct_match.group(1))
            reqs.append(
                ExtractedRequirement(
                    category="gpa",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"minimum": val, "scale": 100.0, "type": "PERCENTAGE"},
                    operator=">=",
                    evidence=_clean_span(
                        combined_text, pct_match.start(), pct_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # 3. Class standing / Honors (First Class, 2:1, Grade A, Top 10%)
        honors_match = re.search(
            r"(?i)\b(first\s+class\s+honours?|upper\s+second[- ]class(?:\s+2:1)?|top\s+10%|grade\s+a|تقدير\s+جيد\s+جداً)\b",
            combined_text,
        )
        if honors_match:
            reqs.append(
                ExtractedRequirement(
                    category="gpa",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={
                        "honors": honors_match.group(1).strip(),
                        "type": "HONORS",
                    },
                    operator=">=",
                    evidence=_clean_span(
                        combined_text, honors_match.start(), honors_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # 4. Qualitative Academic Record
        qual_match = re.search(
            r"(?i)\b(excellent\s+academic\s+record|high\s+academic\s+standing|outstanding\s+academic\s+achievement|سجل\s+أكاديمي\s+ممتاز|تفوق\s+أكاديمي)\b",
            combined_text,
        )
        if qual_match:
            reqs.append(
                ExtractedRequirement(
                    category="gpa",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={
                        "description": qual_match.group(1).strip(),
                        "type": "QUALITATIVE",
                    },
                    evidence=_clean_span(
                        combined_text, qual_match.start(), qual_match.end()
                    ),
                    confidence=ConfidenceLevel.MEDIUM,
                    source_field="description",
                )
            )
            return reqs

        # 5. Missing GPA -> UNKNOWN (Never NOT_REQUIRED)
        reqs.append(
            ExtractedRequirement(
                category="gpa",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.ADMISSION,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    # ========================================================================
    # 5. Language Requirement Extractor
    # ========================================================================

    def _extract_language(self, full_text: str) -> list[ExtractedRequirement]:
        """Extracts language tests and compound OR conditions (e.g. IELTS 6.5 OR TOEFL 80)."""
        reqs: list[ExtractedRequirement] = []

        # Check explicit no language certificate needed
        no_lang_match = re.search(
            r"(?i)\b(?:no\s+(?:ielts(?:\s+certificate)?|toefl(?:\s+certificate)?|language\s+certificate)\s+(?:is\s+)?required|بدون\s+(?:شهادة\s+)?لغة|لا\s+تشترط\s+شهادة\s+لغة)\b",
            full_text,
        )
        if no_lang_match:
            reqs.append(
                ExtractedRequirement(
                    category="language",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"no_certificate_required": True},
                    evidence=_clean_span(
                        full_text, no_lang_match.start(), no_lang_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Look for IELTS and TOEFL
        ielts_match = re.search(
            r"(?i)\bielts\s*(?:score\s+of\s+(?:at\s+least\s+)?|of\s+(?:at\s+least\s+)?|at\s+least\s+|>=|:\s*|minimum\s+)?([5-9](?:\.[05])?)\b",
            full_text,
        )
        toefl_match = re.search(
            r"(?i)\btoefl(?:\s+ibt)?\s*(?:score\s+of\s+(?:at\s+least\s+)?|of\s+(?:at\s+least\s+)?|at\s+least\s+|>=|:\s*|minimum\s+)?([6-9]\d|1[01]\d|120)\b",
            full_text,
        )

        test_items = []
        evidence_spans = []

        if ielts_match:
            test_items.append(
                {
                    "test": "IELTS",
                    "min_score": float(ielts_match.group(1)),
                    "language": "English",
                }
            )
            evidence_spans.append(
                _clean_span(full_text, ielts_match.start(), ielts_match.end())
            )

        if toefl_match:
            test_items.append(
                {
                    "test": "TOEFL",
                    "min_score": float(toefl_match.group(1)),
                    "language": "English",
                }
            )
            evidence_spans.append(
                _clean_span(full_text, toefl_match.start(), toefl_match.end())
            )

        if len(test_items) > 1:
            # Compound OR condition
            condition_items = [
                {
                    "category": "language",
                    "value": t,
                    "operator": ">=",
                }
                for t in test_items
            ]
            reqs.append(
                ExtractedRequirement(
                    category="language",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"tests": test_items},
                    operator="OR",
                    conditions=RequirementCondition(
                        operator="OR", items=condition_items
                    ),
                    evidence="; ".join(evidence_spans),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs
        elif len(test_items) == 1:
            reqs.append(
                ExtractedRequirement(
                    category="language",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value=test_items[0],
                    operator=">=",
                    evidence=evidence_spans[0],
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # General English / German / French requirement mention
        gen_lang_match = re.search(
            r"(?i)\b(?:proof\s+of\s+|demonstrate\s+)?(english\s+(?:or\s+[a-z]+\s+)?proficiency|english\s+language\s+proficiency|proficiency\s+in\s+english|language\s+(?:proficiency\s+)?certificates?|language\s+requirements?|german\s+language\s+proficiency|french\s+language|إتقان\s+اللغة\s+الإنجليزية|شهادة\s+لغة)\b",
            full_text,
        )
        if gen_lang_match:
            reqs.append(
                ExtractedRequirement(
                    category="language",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"description": gen_lang_match.group(1).strip()},
                    evidence=_clean_span(
                        full_text, gen_lang_match.start(), gen_lang_match.end()
                    ),
                    confidence=ConfidenceLevel.MEDIUM,
                    source_field="description",
                )
            )
            return reqs

        # Silent -> UNKNOWN
        reqs.append(
            ExtractedRequirement(
                category="language",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.ADMISSION,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    # ========================================================================
    # 6. Work & Research Experience Extractor
    # ========================================================================

    def _extract_experience(
        self, full_text: str, opportunity_type: str
    ) -> list[ExtractedRequirement]:
        """Extracts work and research experience without inferring from titles or degree levels."""
        reqs: list[ExtractedRequirement] = []

        # Check explicitly no experience required
        no_exp_match = re.search(
            r"(?i)\b(?:no\s+(?:prior|previous)?\s*(?:work|professional|employment)?\s*experience\s+(?:is\s+)?required|بدون\s+خبرة|لا\s+يشترط\s+(?:وجود\s+)?خبرة)\b",
            full_text,
        )
        if no_exp_match:
            reqs.append(
                ExtractedRequirement(
                    category="experience",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"no_experience_required": True},
                    evidence=_clean_span(
                        full_text, no_exp_match.start(), no_exp_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Explicit minimum years or hours
        word_to_num = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        years_match = re.search(
            r"(?i)\b(?:at\s+least|minimum\s+(?:of\s+)?)?\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+years?(?:\s+of)?\s+(?:full[- ]time\s+)?(?:(?:work|professional|relevant|volunteer|employment|research)(?:\s+(?:or|and)\s+(?:work|professional|relevant|volunteer|employment|research))?)\s+experience\b",
            full_text,
        )
        if years_match:
            raw_str = years_match.group(1).lower()
            min_yrs = int(raw_str) if raw_str.isdigit() else word_to_num.get(raw_str, 1)
            reqs.append(
                ExtractedRequirement(
                    category="experience",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"minimum_years": min_yrs},
                    operator=">=",
                    evidence=_clean_span(
                        full_text, years_match.start(), years_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        hours_match = re.search(
            r"(?i)\b(\d{1,2},?\d{3})\s+hours\s+of\s+(?:work|employment)\s+experience\b",
            full_text,
        )
        if hours_match:
            hrs = int(hours_match.group(1).replace(",", ""))
            reqs.append(
                ExtractedRequirement(
                    category="experience",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"minimum_hours": hrs},
                    operator=">=",
                    evidence=_clean_span(
                        full_text, hours_match.start(), hours_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Explicit preferred experience
        pref_match = re.search(
            r"(?i)\b(?:previous|relevant)?\s*(?:work|research)\s+experience\s+(?:is\s+)?(?:preferred|an\s+advantage|desirable)|أفضلية\s+لأصحاب\s+الخبرة\b",
            full_text,
        )
        if pref_match:
            reqs.append(
                ExtractedRequirement(
                    category="experience",
                    status=RequirementStatus.PREFERRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"preferred": True},
                    evidence=_clean_span(
                        full_text, pref_match.start(), pref_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Silent -> UNKNOWN (Do not infer from opportunity_type = fellowship or internship)
        reqs.append(
            ExtractedRequirement(
                category="experience",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.SCHOLARSHIP,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    # ========================================================================
    # 7. Age Extractor
    # ========================================================================

    def _extract_age(self, full_text: str) -> list[ExtractedRequirement]:
        """Extracts explicit numeric age restrictions, rejecting vague phrases like 'young'."""
        reqs: list[ExtractedRequirement] = []

        # Explicit maximum age (e.g. under 30 years old, maximum age 28, أقل من 30 عاماً)
        max_age_match = re.search(
            r"(?i)\b(?:under(?:\s+the\s+age\s+of)?|maximum\s+age\s+(?:of\s+)?|no\s+older\s+than|أقل\s+من|لا\s+يتجاوز|لا\s+يزيد\s+عن)\s*(\d{2})\s*(?:years(?:\s+old)?|عاماً?|سنة)?\b",
            full_text,
        )
        if max_age_match:
            age_val = int(max_age_match.group(1))
            if 15 <= age_val <= 60:
                reqs.append(
                    ExtractedRequirement(
                        category="age",
                        status=RequirementStatus.REQUIRED,
                        requirement_type=RequirementType.ELIGIBILITY,
                        scope=RequirementScope.SCHOLARSHIP,
                        value={"maximum": age_val},
                        operator="<=",
                        evidence=_clean_span(
                            full_text, max_age_match.start(), max_age_match.end()
                        ),
                        confidence=ConfidenceLevel.HIGH,
                        source_field="description",
                    )
                )
                return reqs

        # Explicit age range (e.g. aged 18-25, aged between 21 and 27)
        range_match = re.search(
            r"(?i)\b(?:aged\s+(?:between\s+)?|age\s+between)\s*(\d{2})\s*(?:-|to|and|وحتى)\s*(\d{2})\b",
            full_text,
        )
        if range_match:
            min_a = int(range_match.group(1))
            max_a = int(range_match.group(2))
            reqs.append(
                ExtractedRequirement(
                    category="age",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"minimum": min_a, "maximum": max_a},
                    evidence=_clean_span(
                        full_text, range_match.start(), range_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Birth date cutoff (e.g. born after January 1, 1995 or born after 31 December 1989)
        birth_match = re.search(
            r"(?i)\bborn\s+after\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})\b",
            full_text,
        )
        if birth_match:
            reqs.append(
                ExtractedRequirement(
                    category="age",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"birth_date_after": birth_match.group(1)},
                    evidence=_clean_span(
                        full_text, birth_match.start(), birth_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        # Silent -> UNKNOWN (Do not infer from "young professionals" or "emerging leaders")
        reqs.append(
            ExtractedRequirement(
                category="age",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.SCHOLARSHIP,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    # ========================================================================
    # 8. Skills & Interests Extractor
    # ========================================================================

    def _extract_skills(
        self, eligibility_text: str, description: str
    ) -> list[ExtractedRequirement]:
        """Extracts applicant skills, validating that text describes the applicant not program curriculum."""
        reqs: list[ExtractedRequirement] = []
        combined_text = f"{eligibility_text}\n{description}"

        # Look for applicant leadership, extracurricular, or technical capability statements
        skill_match = re.search(
            r"(?i)\b(?:demonstrate\s+|proven\s+|possess\s+)?(leadership\s+skills|leadership\s+potential|community\s+involvement|extracurricular\s+activities|strong\s+analytical\s+skills|مهارات\s+قيادية|أنشطة\s+تطوعية)\b",
            combined_text,
        )
        if skill_match:
            # Check context: reject if it's program learning outcome ("The program teaches leadership", "participants will learn")
            matched_span = _clean_span(
                combined_text, skill_match.start(), skill_match.end()
            )
            if re.search(
                r"(?i)\b(program\s+teaches|will\s+learn|curriculum\s+covers|يقدم\s+البرنامج\s+تدريب)\b",
                matched_span,
            ):
                reqs.append(
                    ExtractedRequirement(
                        category="skills",
                        status=RequirementStatus.UNKNOWN,
                        requirement_type=RequirementType.ELIGIBILITY,
                        scope=RequirementScope.SCHOLARSHIP,
                        evidence=None,
                        confidence=ConfidenceLevel.LOW,
                        source_field="description",
                    )
                )
                return reqs

            is_mandatory = bool(
                re.search(
                    r"(?i)\b(must\s+demonstrate|required|essential|يجب)\b",
                    matched_span,
                )
            )
            reqs.append(
                ExtractedRequirement(
                    category="skills",
                    status=(
                        RequirementStatus.REQUIRED
                        if is_mandatory
                        else RequirementStatus.PREFERRED
                    ),
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"skill": skill_match.group(1).strip()},
                    evidence=matched_span,
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
            return reqs

        reqs.append(
            ExtractedRequirement(
                category="skills",
                status=RequirementStatus.UNKNOWN,
                requirement_type=RequirementType.ELIGIBILITY,
                scope=RequirementScope.SCHOLARSHIP,
                evidence=None,
                confidence=ConfidenceLevel.LOW,
                source_field="description",
            )
        )
        return reqs

    # ========================================================================
    # 9. Gender & Financial Need Extractors
    # ========================================================================

    def _extract_gender(self, full_text: str) -> list[ExtractedRequirement]:
        """Extracts explicit gender requirements (e.g. female only)."""
        reqs: list[ExtractedRequirement] = []
        female_match = re.search(
            r"(?i)\b(open\s+to\s+female\s+applicants|women\s+only|for\s+female\s+students|مخصصة\s+للإناث|للنساء\s+فقط)\b",
            full_text,
        )
        if female_match:
            reqs.append(
                ExtractedRequirement(
                    category="gender",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"gender": "female"},
                    evidence=_clean_span(
                        full_text, female_match.start(), female_match.end()
                    ),
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
        return reqs

    def _extract_financial_need(self, full_text: str) -> list[ExtractedRequirement]:
        """Extracts explicit financial need requirements."""
        reqs: list[ExtractedRequirement] = []
        need_match = re.search(
            r"(?i)\b(must\s+demonstrate\s+financial\s+need|demonstrate\s+financial\s+need|based\s+on\s+financial\s+need|priority\s+given\s+to\s+low-income|حاجة\s+مالية|ذوي\s+الدخل\s+المحدود)\b",
            full_text,
        )
        if need_match:
            span_text = _clean_span(full_text, need_match.start(), need_match.end())
            is_mandatory = bool(
                re.search(
                    r"(?i)\b(must\s+demonstrate|required|mandatory|شرط)\b",
                    span_text,
                )
            )
            reqs.append(
                ExtractedRequirement(
                    category="financial_need",
                    status=(
                        RequirementStatus.REQUIRED
                        if is_mandatory
                        else RequirementStatus.PREFERRED
                    ),
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.SCHOLARSHIP,
                    value={"financial_need_required": True},
                    evidence=span_text,
                    confidence=ConfidenceLevel.HIGH,
                    source_field="description",
                )
            )
        return reqs

    # ========================================================================
    # 10. Application Requirements Extractor
    # ========================================================================

    def _extract_application_documents(
        self, full_text: str
    ) -> list[ExtractedRequirement]:
        """Extracts required application documents (letters, proposals, transcripts)."""
        reqs: list[ExtractedRequirement] = []
        doc_patterns = [
            (
                r"(?i)\b(?:(?:submit|provide|require[sd]?)\s*(?:at\s+least\s+)?)?(\d+)?\s*(?:letters?\s+of\s+recommendation|recommendation\s+letters?|خطابات?\s+توصية)\b",
                "recommendation_letter",
            ),
            (
                r"(?i)\b(motivation\s+letter|personal\s+statement|statement\s+of\s+purpose|خطاب\s+دافع|رسالة\s+تغطية)\b",
                "motivation_letter",
            ),
            (
                r"(?i)\b(research\s+proposal|مقترح\s+بحثي|خطة\s+بحث)\b",
                "research_proposal",
            ),
            (
                r"(?i)\b(academic\s+transcripts?|transcripts?|koc\s+transcript|كشف\s+علامات|بيان\s+درجات)\b",
                "transcript",
            ),
        ]

        for pat, doc_name in doc_patterns:
            m = re.search(pat, full_text)
            if m:
                qty = (
                    int(m.group(1))
                    if m.groups() and m.group(1) and m.group(1).isdigit()
                    else 1
                )
                reqs.append(
                    ExtractedRequirement(
                        category="application",
                        status=RequirementStatus.REQUIRED,
                        requirement_type=RequirementType.APPLICATION,
                        scope=RequirementScope.APPLICATION,
                        value={"document": doc_name, "quantity": qty},
                        evidence=_clean_span(full_text, m.start(), m.end()),
                        confidence=ConfidenceLevel.HIGH,
                        source_field="description",
                    )
                )

        return reqs
