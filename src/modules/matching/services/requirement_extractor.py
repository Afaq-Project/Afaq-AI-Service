"""Requirement extractor for Afaq AI Matching Engine.

Extracts structured eligibility requirements from scholarship text using
deterministic regex patterns. No LLM or ML required.
"""

import logging
import re
from typing import Any

from src.modules.matching.models import (
    OPEN_TO_ALL_NATIONALITIES,
    ConfidenceLevel,
    ExtractedRequirement,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementStatus,
    RequirementType,
)
from src.modules.scraping.services.normalization_service import (
    COUNTRY_MAPPINGS,
    NormalizationService,
)

logger = logging.getLogger(__name__)

# Tokens that indicate a field string is noise, not an academic discipline
NON_ACADEMIC_FIELD_TOKENS: frozenset[str] = frozenset(
    {
        "scholarship",
        "scholarships",
        "studentship",
        "fellowship",
        "fellowships",
        "internship",
        "internships",
        "grant",
        "grants",
        "study in",
        "study abroad",
        "travel to",
        "fully funded",
        "partially funded",
        "financial aid",
        "university of",
        "institute of",
        "college of",
        "europe",
        "european",
        "america",
        "american",
        "asia",
        "asian",
        "middle east",
        "africa",
        "african",
        "oceania",
        "caribbean",
        "international students",
        "women scholarships",
    }
)


def _clean_span(text: str, start: int, end: int, max_len: int = 200) -> str:
    """Returns a cleaned evidence snippet centred on [start:end]."""
    lo = max(0, start - 30)
    hi = min(len(text), end + 60)
    return text[lo:hi].strip()[:max_len]


class RequirementExtractor:
    """Extracts structured requirements from scholarship text.

    All extraction is deterministic (regex-based). No LLM is used.
    When a requirement type cannot be reliably extracted, it is either
    omitted or included with UNKNOWN status and LOW confidence.
    """

    def __init__(self, normalizer: NormalizationService | None = None) -> None:
        self._norm = normalizer or NormalizationService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, opportunity: dict[str, Any]) -> OpportunityRequirementsDTO:
        """Extracts all supported requirements from an opportunity dict.

        Reads: title, description, eligibility (dict or str), study_levels,
        fields_of_study, opportunity_type.

        Returns OpportunityRequirementsDTO with all found requirements.
        """
        opp_id = str(opportunity.get("id") or opportunity.get("opportunity_id") or "")
        title = str(opportunity.get("title") or "")

        # Collect all text sources
        description = str(opportunity.get("description") or "")
        eligibility_raw = opportunity.get("eligibility") or {}
        if isinstance(eligibility_raw, str):
            eligibility_text = eligibility_raw
        elif isinstance(eligibility_raw, dict):
            eligibility_text = eligibility_raw.get("eligibility_text") or ""
        else:
            eligibility_text = ""

        study_levels: list[str] = opportunity.get("study_levels") or []
        fields_of_study: list[str] = opportunity.get("fields_of_study") or []
        opportunity_type: str = str(opportunity.get("opportunity_type") or "")

        full_text = "\n".join(filter(None, [title, eligibility_text, description]))

        requirements: list[ExtractedRequirement] = []

        # Extract each requirement type
        requirements.extend(
            self._extract_nationality(eligibility_text, description, full_text)
        )
        requirements.extend(self._extract_education(study_levels, full_text, title))
        requirements.extend(self._extract_field_of_study(fields_of_study, full_text))
        requirements.extend(self._extract_gpa(eligibility_text, description))
        requirements.extend(self._extract_language(full_text))
        requirements.extend(self._extract_experience(full_text, opportunity_type))
        requirements.extend(self._extract_age(full_text))
        requirements.extend(self._extract_gender(full_text))
        requirements.extend(self._extract_financial_need(full_text))

        return OpportunityRequirementsDTO(
            opportunity_id=opp_id or None,
            title=title or None,
            requirements=requirements,
        )

    # ------------------------------------------------------------------
    # Private extractors
    # ------------------------------------------------------------------

    def _extract_nationality(
        self,
        eligibility_text: str,
        description: str,
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts nationality eligibility requirements.

        Sources (priority order):
        1. Structured eligible_nationalities list (already parsed by adapters).
        2. 'Target group:' / 'Eligible Nationality:' labeled text.
        3. Regex patterns for inclusion / exclusion / open-to-all.
        """
        results: list[ExtractedRequirement] = []

        # Pattern: open to all
        open_pattern = re.compile(
            r"(?i)\b(?:open\s+to\s+all\s+(?:nationalities|countries|international\s+students)?|"
            r"students\s+from\s+all\s+(?:over\s+the\s+world|countries)|worldwide|global)",
        )
        m = open_pattern.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.NATIONALITY,
                    status=RequirementStatus.NOT_REQUIRED,
                    condition=None,
                    value="open_to_all",
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Open to all nationalities",
                    confidence=ConfidenceLevel.HIGH,
                )
            )
            return results

        # Pattern: 'citizens of / nationals of / students from [country]'
        country_req_pattern = re.compile(
            r"(?i)\b(?:citizens?\s+of|nationals?\s+of|students?\s+from|applicants?\s+from)\s+([A-Z][^.\n,;]{3,60})",
        )
        # Pattern: 'Target group: [text]' from Scholars4Dev
        target_group_pattern = re.compile(
            r"(?i)(?:Target\s+group[s]?|Eligible\s+Nationalit(?:y|ies)|Eligible\s+Countr(?:y|ies))[:\s]+([^\n]{5,300})",
        )
        # Pattern: exclusion — 'not [country] citizens'
        exclusion_pattern = re.compile(
            r"(?i)\b(?:non[-\s](?:Chinese|Italian|US|UK|Canadian|Australian|German|French|Japanese|Korean|Turkish|Egyptian|Saudi|Emirati|Qatari)\s+citizens?|not?\s+(?:a\s+)?(?:United\s+States?|US|UK|British)\s+citizens?)",
        )

        # Try target group pattern first
        m = target_group_pattern.search(eligibility_text or full_text)
        if m:
            raw = m.group(1).strip()
            # Map country names to normalized
            countries = self._parse_country_list(raw)
            is_open = (
                any(tok in raw.lower() for tok in OPEN_TO_ALL_NATIONALITIES)
                or "any country" in raw.lower()
                or "all countries" in raw.lower()
            )
            if countries or is_open:
                results.append(
                    ExtractedRequirement(
                        req_type=RequirementType.NATIONALITY,
                        status=RequirementStatus.REQUIRED
                        if not is_open
                        else RequirementStatus.NOT_REQUIRED,
                        condition=RequirementCondition.IN if not is_open else None,
                        value=countries if not is_open else "open_to_all",
                        raw_value=_clean_span(
                            eligibility_text or full_text, m.start(), m.end()
                        ),
                        description=f"Eligible nationalities: {', '.join(countries[:5])}"
                        if not is_open
                        else "Open to all nationalities",
                        confidence=ConfidenceLevel.HIGH,
                    )
                )
                return results

        # Try citizens/nationals pattern
        m = country_req_pattern.search(eligibility_text or full_text)
        if m:
            raw = m.group(1).strip()
            countries = self._parse_country_list(raw)
            if countries:
                results.append(
                    ExtractedRequirement(
                        req_type=RequirementType.NATIONALITY,
                        status=RequirementStatus.REQUIRED,
                        condition=RequirementCondition.IN,
                        value=countries,
                        raw_value=_clean_span(full_text, m.start(), m.end()),
                        description=f"Applicant must be from: {', '.join(countries[:5])}",
                        confidence=ConfidenceLevel.MEDIUM,
                    )
                )
                return results

        # Exclusion pattern
        m = exclusion_pattern.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.NATIONALITY,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.NOT_IN,
                    value=m.group(0).strip(),
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description=f"Nationality exclusion: {m.group(0).strip()}",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )
            return results

        return results

    def _parse_country_list(self, raw: str) -> list[str]:
        """Splits a country list string and normalizes each country name."""
        # Split on commas, semicolons, 'and', bullets
        parts = re.split(r"[,;\u060c]|\band\b|\u2022", raw)
        countries: list[str] = []
        for part in parts:
            clean = part.strip().rstrip(".").strip()
            if not clean or len(clean) < 2:
                continue
            # Normalize via country mappings
            lower = clean.lower()
            normalized = COUNTRY_MAPPINGS.get(lower)
            if normalized:
                countries.append(normalized)
            elif len(clean) > 2:  # Passthrough for unknown countries
                countries.append(clean.title())
        return countries[:30]  # Cap at 30 to avoid noise

    def _extract_education(
        self,
        study_levels: list[str],
        full_text: str,
        title: str,
    ) -> list[ExtractedRequirement]:
        """Extracts study / degree level requirements."""
        results: list[ExtractedRequirement] = []

        if study_levels:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.EDUCATION,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.IN,
                    value=study_levels,
                    raw_value=f"study_levels: {study_levels}",
                    description=f"Required degree level(s): {', '.join(study_levels)}",
                    confidence=ConfidenceLevel.HIGH,
                )
            )
            return results

        # Fallback: detect from text
        level_patterns = [
            (
                "Bachelor",
                re.compile(r"(?i)\b(?:bachelor'?s?|undergraduate|بكالوريوس)\b"),
            ),
            (
                "Master",
                re.compile(r"(?i)\b(?:master'?s?|postgraduate|ماجستير|msc|mba)\b"),
            ),
            ("PhD", re.compile(r"(?i)\b(?:ph\.?d\.?|doctorate|doctoral|دكتوراه)\b")),
        ]
        found = []
        for level_name, pattern in level_patterns:
            if pattern.search(full_text):
                found.append(level_name)

        if found:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.EDUCATION,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.IN,
                    value=found,
                    raw_value="description",
                    description=f"Required degree level(s) from text: {', '.join(found)}",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )

        return results

    def _extract_field_of_study(
        self,
        fields_of_study: list[str],
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts academic disciplines while strictly rejecting geographic and metadata noise."""

        # Open-to-all field pattern
        open_field_pattern = re.compile(
            r"(?i)\b(?:open\s+to\s+all\s+(?:academic\s+)?(?:fields|disciplines|subjects|majors)|any\s+(?:eligible\s+)?(?:academic\s+)?(?:field|discipline|subject|course)|open\s+to\s+any\s+subject|all\s+academic\s+fields)",
        )
        if open_field_pattern.search(full_text):
            return [
                ExtractedRequirement(
                    req_type=RequirementType.FIELD_OF_STUDY,
                    status=RequirementStatus.NOT_REQUIRED,
                    condition=None,
                    value="open_to_all",
                    raw_value="open_to_all",
                    description="Opportunity explicitly has no field of study restrictions (neutral/waived)",
                    confidence=ConfidenceLevel.HIGH,
                )
            ]

        if not fields_of_study:
            return []

        valid_fields = [
            f
            for f in fields_of_study
            if f and not any(tok in f.lower() for tok in NON_ACADEMIC_FIELD_TOKENS)
        ]
        if not valid_fields:
            return []

        return [
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=valid_fields,
                raw_value=f"fields_of_study: {valid_fields}",
                description=f"Required field(s) of study: {', '.join(valid_fields[:5])}",
                confidence=ConfidenceLevel.HIGH,
            )
        ]

    def _extract_gpa(
        self,
        eligibility_text: str,
        description: str,
    ) -> list[ExtractedRequirement]:
        """Extracts GPA, percentage, honors standing, or qualitative academic requirements."""
        results: list[ExtractedRequirement] = []
        search_text = f"{eligibility_text}\n{description}"

        # GPA on 4.0 scale: e.g. 'GPA of 3.5', 'minimum GPA 3.0/4.0'
        gpa_pattern = re.compile(
            r"(?i)\b(?:minimum\s+)?(?:c?gpa|agpa)\s+(?:of\s+|>=|:\s*)?([2-4](?:\.\d+)?)(?:\s*(?:/|\s+out\s+of\s+)(4(?:\.0)?))?\b"
        )
        m = gpa_pattern.search(search_text)
        if m:
            raw_val = float(m.group(1))
            scale = float(m.group(2)) if m.group(2) else 4.0
            gpa_4 = raw_val if scale == 4.0 else (raw_val / scale) * 4.0
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.GTE,
                    value={
                        "min_gpa_normalized_4": round(gpa_4, 2),
                        "minimum": raw_val,
                        "scale": scale,
                        "type": "NUMERIC",
                    },
                    raw_value=_clean_span(search_text, m.start(), m.end()),
                    description=f"Minimum GPA {raw_val}/{scale}",
                    confidence=ConfidenceLevel.HIGH,
                )
            )
            return results

        # Percentage GPA: e.g. '75% or higher'
        pct_pattern = re.compile(
            r"(?i)\b(?:minimum\s+)?(?:academic\s+)?(?:average|grade)?\s*(?:of)?\s*([6-9]\d)%\s*(?:or\s+higher)?\b"
        )
        m = pct_pattern.search(search_text)
        if m:
            pct = float(m.group(1))
            gpa_4 = (pct / 100.0) * 4.0
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.GTE,
                    value={
                        "min_gpa_normalized_4": round(gpa_4, 2),
                        "minimum": pct,
                        "scale": 100.0,
                        "type": "PERCENTAGE",
                    },
                    raw_value=_clean_span(search_text, m.start(), m.end()),
                    description=f"Minimum academic average {pct}%",
                    confidence=ConfidenceLevel.HIGH,
                )
            )
            return results

        # Honors / qualitative: 'First Class Honours', 'Upper Second'
        honors_pattern = re.compile(
            r"(?i)\b(first\s+class\s+honours?|upper\s+second[- ]class(?:\s+2:1)?|top\s+10%|grade\s+a)\b"
        )
        m = honors_pattern.search(search_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    condition=None,
                    value={"honors": m.group(1).strip(), "type": "HONORS"},
                    raw_value=_clean_span(search_text, m.start(), m.end()),
                    description=f"Academic standing: {m.group(1).strip()}",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )
            return results

        # Qualitative: 'excellent academic record'
        qualitative_pattern = re.compile(
            r"(?i)\b(excellent\s+academic\s+record|high\s+academic\s+standing|outstanding\s+academic\s+achievement)\b"
        )
        m = qualitative_pattern.search(search_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.PREFERRED,
                    condition=None,
                    value={"text": m.group(1).strip(), "type": "QUALITATIVE"},
                    raw_value=_clean_span(search_text, m.start(), m.end()),
                    description=f"Qualitative academic requirement: {m.group(1).strip()}",
                    confidence=ConfidenceLevel.LOW,
                )
            )
            return results

        return results

    def _extract_language(
        self,
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts language tests and compound OR conditions (e.g. IELTS 6.5 OR TOEFL 80)."""
        results: list[ExtractedRequirement] = []

        # Explicit no certificate required
        no_cert_pattern = re.compile(
            r"(?i)\b(?:no\s+(?:ielts(?:\s+certificate)?|toefl(?:\s+certificate)?|language\s+certificate)\s+(?:is\s+)?required|ielts\s+(?:is\s+)?(?:not\s+)?waived)\b"
        )
        if no_cert_pattern.search(full_text):
            return [
                ExtractedRequirement(
                    req_type=RequirementType.LANGUAGE,
                    status=RequirementStatus.NOT_REQUIRED,
                    condition=None,
                    value="no_certificate_required",
                    raw_value="no_certificate_required",
                    description="Opportunity explicitly has no language certificate restrictions (neutral/waived)",
                    confidence=ConfidenceLevel.HIGH,
                )
            ]

        tests: list[dict[str, Any]] = []

        # IELTS
        ielts_pattern = re.compile(
            r"(?i)\bielts\s*(?:score\s+of\s+(?:at\s+least\s+)?|of\s+(?:at\s+least\s+)?|at\s+least\s+|>=|:\s*|minimum\s+)?([5-9](?:\.[05])?)\b"
        )
        for m in ielts_pattern.finditer(full_text):
            tests.append(
                {
                    "test": "IELTS",
                    "min_score": float(m.group(1)),
                    "category": "English",
                    "value": float(m.group(1)),
                    "operator": "gte",
                }
            )

        # TOEFL
        toefl_pattern = re.compile(
            r"(?i)\btoefl(?:\s+ibt)?\s*(?:score\s+of\s+(?:at\s+least\s+)?|of\s+(?:at\s+least\s+)?|at\s+least\s+|>=|:\s*|minimum\s+)?([6-9]\d|1[01]\d|120)\b"
        )
        for m in toefl_pattern.finditer(full_text):
            tests.append(
                {
                    "test": "TOEFL",
                    "min_score": float(m.group(1)),
                    "category": "English",
                    "value": float(m.group(1)),
                    "operator": "gte",
                }
            )

        # Duolingo
        duolingo_pattern = re.compile(
            r"(?i)\bduolingo(?:\s+english\s+test)?\s*(?:score\s+of\s+(?:at\s+least\s+)?|of\s+(?:at\s+least\s+)?|at\s+least\s+|>=|:\s*|minimum\s+)?(\d{2,3})\b"
        )
        for m in duolingo_pattern.finditer(full_text):
            tests.append(
                {
                    "test": "Duolingo",
                    "min_score": float(m.group(1)),
                    "category": "English",
                    "value": float(m.group(1)),
                    "operator": "gte",
                }
            )

        if tests:
            # Deduplicate by test name (keep highest min_score)
            by_test: dict[str, dict[str, Any]] = {}
            for t in tests:
                name = t["test"]
                if name not in by_test or t["min_score"] > by_test[name]["min_score"]:
                    by_test[name] = t
            tests = list(by_test.values())

            return [
                ExtractedRequirement(
                    req_type=RequirementType.LANGUAGE,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.GTE,
                    value={"tests": tests},
                    raw_value="tests",
                    description=f"Language test required: {', '.join(t['test'] + ' ' + str(t['min_score']) for t in tests)}",
                    confidence=ConfidenceLevel.HIGH,
                )
            ]

        # General English proficiency (no specific test score)
        general_lang_pattern = re.compile(
            r"(?i)\b(?:proof\s+of\s+|demonstrate\s+)?(?:english\s+(?:or\s+[a-z]+\s+)?proficiency|english\s+language\s+proficiency|proficiency\s+in\s+english|language\s+(?:proficiency\s+)?certificates?|language\s+requirements?)\b"
        )
        m = general_lang_pattern.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.LANGUAGE,
                    status=RequirementStatus.REQUIRED,
                    condition=None,
                    value={
                        "tests": [],
                        "min_proficiency": "proficient",
                        "category": "English",
                    },
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="English language proficiency required (no specific test score)",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )

        return results

    def _extract_experience(
        self,
        full_text: str,
        opportunity_type: str,
    ) -> list[ExtractedRequirement]:
        """Extracts work and research experience without inferring from titles or degree levels."""
        results: list[ExtractedRequirement] = []

        # No experience required
        no_exp_pattern = re.compile(
            r"(?i)\b(?:no\s+(?:prior|previous)?\s*(?:work|professional|employment)?\s*experience\s+(?:is\s+)?required)\b"
        )
        if no_exp_pattern.search(full_text):
            return [
                ExtractedRequirement(
                    req_type=RequirementType.EXPERIENCE,
                    status=RequirementStatus.NOT_REQUIRED,
                    condition=None,
                    value="no_experience_required",
                    raw_value="no_experience_required",
                    description="Opportunity explicitly has no experience restrictions (neutral/waived)",
                    confidence=ConfidenceLevel.HIGH,
                )
            ]

        # Specific experience area patterns (REQUIRED or PREFERRED)
        area_patterns = [
            (
                "research",
                re.compile(
                    r"(?i)\b(?:research\s+experience|research\s+background|research\s+assistant)\b"
                ),
            ),
            (
                "volunteering",
                re.compile(
                    r"(?i)\b(?:volunteer(?:ing)?\s+experience|community\s+service)\b"
                ),
            ),
            (
                "teaching",
                re.compile(
                    r"(?i)\b(?:teaching\s+experience|tutoring|academic\s+instruction)\b"
                ),
            ),
            (
                "clinical",
                re.compile(r"(?i)\b(?:clinical\s+experience|medical\s+practice)\b"),
            ),
            (
                "leadership",
                re.compile(r"(?i)\b(?:leadership\s+experience|student\s+leadership)\b"),
            ),
            (
                "work",
                re.compile(
                    r"(?i)\b(?:work|professional|employment|industry)\s+experience\b"
                ),
            ),
        ]

        for area_name, pattern in area_patterns:
            m = pattern.search(full_text)
            if m:
                snippet = _clean_span(full_text, m.start(), m.end(), 120)
                is_preferred = bool(
                    re.search(
                        r"(?i)\b(?:preferred|advantage|desirable|plus|optionally)\b",
                        snippet,
                    )
                )
                results.append(
                    ExtractedRequirement(
                        req_type=RequirementType.EXPERIENCE,
                        status=RequirementStatus.PREFERRED
                        if is_preferred
                        else RequirementStatus.REQUIRED,
                        condition=None,
                        value={"area": area_name},
                        raw_value=snippet,
                        description=f"{area_name.title()} experience {'preferred' if is_preferred else 'required'}",
                        confidence=ConfidenceLevel.HIGH
                        if not is_preferred
                        else ConfidenceLevel.MEDIUM,
                    )
                )
                return results

        # Generic experience mention ("must have relevant experience" / "experience preferred")
        generic_required = re.compile(
            r"(?i)\b(?:must\s+have|required\s+to\s+have)\s+(?:prior|previous|relevant)\s+experience\b"
        )
        m = generic_required.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.EXPERIENCE,
                    status=RequirementStatus.REQUIRED,
                    condition=None,
                    value={"area": "relevant_experience"},
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Relevant experience required",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )
            return results

        generic_preferred = re.compile(
            r"(?i)\b(?:previous|relevant)?\s*(?:work|research)?\s*experience\s+(?:is\s+)?(?:preferred|an\s+advantage|desirable)\b"
        )
        m = generic_preferred.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.EXPERIENCE,
                    status=RequirementStatus.PREFERRED,
                    condition=None,
                    value={"area": "relevant_experience"},
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Relevant experience preferred (not required)",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            )

        return results

    def _extract_age(
        self,
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts explicit numeric age restrictions, rejecting vague phrases like 'young'."""
        results: list[ExtractedRequirement] = []

        # Maximum age: 'under 35', 'no older than 40', 'maximum age of 35'
        max_age_pattern = re.compile(
            r"(?i)\b(?:under(?:\s+the\s+age\s+of)?|maximum\s+age\s+(?:of\s+)?|no\s+older\s+than)\s*(\d{2})\s*(?:years(?:\s+old)?)?"
        )
        m = max_age_pattern.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.AGE,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.LTE,
                    value={"maximum": int(m.group(1))},
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description=f"Maximum age: {m.group(1)}",
                    confidence=ConfidenceLevel.HIGH,
                )
            )
            return results

        # Age range: 'aged 18-24', 'age between 25 and 35'
        range_pattern = re.compile(
            r"(?i)\b(?:aged\s+(?:between\s+)?|age\s+between)\s*(\d{2})\s*(?:-|to|and)\s*(\d{2})\b"
        )
        m = range_pattern.search(full_text)
        if m:
            results.append(
                ExtractedRequirement(
                    req_type=RequirementType.AGE,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.IN,
                    value={"minimum": int(m.group(1)), "maximum": int(m.group(2))},
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description=f"Age between {m.group(1)} and {m.group(2)}",
                    confidence=ConfidenceLevel.HIGH,
                )
            )

        return results

    def _extract_gender(
        self,
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts explicit gender requirements (e.g. female only)."""
        gender_pattern = re.compile(
            r"(?i)\b(?:open\s+to\s+female\s+applicants|women\s+only|for\s+female\s+students|women\s+who\s+are\s+not|female\s+candidates\s+only)\b"
        )
        m = gender_pattern.search(full_text)
        if m:
            return [
                ExtractedRequirement(
                    req_type=RequirementType.GENDER,
                    status=RequirementStatus.REQUIRED,
                    condition=RequirementCondition.EQ,
                    value="female",
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Restricted to female applicants",
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        return []

    def _extract_financial_need(
        self,
        full_text: str,
    ) -> list[ExtractedRequirement]:
        """Extracts explicit financial need requirements."""
        required_pattern = re.compile(
            r"(?i)\b(?:must\s+demonstrate\s+financial\s+need|demonstrate\s+financial\s+need|based\s+on\s+financial\s+need|financial\s+need\s+(?:is\s+)?required|priority\s+given\s+to\s+low-income)\b"
        )
        m = required_pattern.search(full_text)
        if m:
            # Determine REQUIRED vs PREFERRED
            context = _clean_span(full_text, m.start(), m.end(), 100).lower()
            is_required = bool(
                re.search(r"(?i)\b(?:must\s+demonstrate|required|mandatory)\b", context)
            )
            return [
                ExtractedRequirement(
                    req_type=RequirementType.FINANCIAL_NEED,
                    status=RequirementStatus.REQUIRED
                    if is_required
                    else RequirementStatus.PREFERRED,
                    condition=RequirementCondition.EQ,
                    value="financial_need_required",
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Financial need required"
                    if is_required
                    else "Financial need preferred",
                    confidence=ConfidenceLevel.HIGH
                    if is_required
                    else ConfidenceLevel.MEDIUM,
                )
            ]

        preferred_pattern = re.compile(
            r"(?i)\b(?:priority(?:\s+given)?\s+to|preference\s+for)\s+(?:students?\s+with\s+)?financial\s+need\b"
        )
        m = preferred_pattern.search(full_text)
        if m:
            return [
                ExtractedRequirement(
                    req_type=RequirementType.FINANCIAL_NEED,
                    status=RequirementStatus.PREFERRED,
                    condition=RequirementCondition.EQ,
                    value="financial_need_preferred",
                    raw_value=_clean_span(full_text, m.start(), m.end()),
                    description="Financial need preferred",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            ]

        return []
