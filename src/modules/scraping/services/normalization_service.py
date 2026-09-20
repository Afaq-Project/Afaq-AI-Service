import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Funding type normalizations
FUNDING_MAPPINGS = [
    (
        re.compile(
            r"(?i)\b(fully[ -]?funded|full[ -]?funding|full[ -]?scholarship|full[ -]?tuition|100%[ -]?funded|ممول[ -]?بالكامل|تمويل[ -]?كامل)\b"
        ),
        "fully_funded",
    ),
    (
        re.compile(
            r"(?i)\b(partially[ -]?funded|partial[ -]?funding|tuition[ -]?(?:fee|waiver)|ممول[ -]?جزئيا|تمويل[ -]?جزئي|خصم|تخفيض)\b"
        ),
        "partially_funded",
    ),
    (
        re.compile(r"(?i)\b(unfunded|self[ -]?funded|غير[ -]?ممول|تمويل[ -]?ذاتي)\b"),
        "unfunded",
    ),
]

# Opportunity type normalizations
OPPORTUNITY_TYPE_MAPPINGS = [
    (re.compile(r"(?i)\b(fellowships?|زميل|زمالة|زمالات)\b"), "fellowship"),
    (
        re.compile(
            r"(?i)\b(internships?|interns?|traineeships?|trainee|تدريب[ -]?عملي|تدريب[ -]?صيفي|تدريب)\b"
        ),
        "internship",
    ),
    (
        re.compile(
            r"(?i)\b(training|bootcamps?|workshops?|دورة[ -]?تدريبية|برنامج[ -]?تدريبي|معسكر)\b"
        ),
        "training",
    ),
    (
        re.compile(r"(?i)\b(volunteering|volunteers?|تطوع|عمل[ -]?تطوعي)\b"),
        "volunteering",
    ),
    (
        re.compile(
            r"(?i)\b(exchange[ -]?(?:programs?|programmes?)?|تبادل[ -]?(?:ثقافي|طلابي)?)\b"
        ),
        "exchange_program",
    ),
    (
        re.compile(r"(?i)\b(competitions?|contests?|hackathons?|مسابقة|هاكاثون)\b"),
        "competition",
    ),
    (re.compile(r"(?i)\b(grants?|awards?|بحث[ -]?علمي|منحة[ -]?بحثية)\b"), "grant"),
    (
        re.compile(
            r"(?i)\b(scholarships?|studentships?|منحة[ -]?دراسية|منح[ -]?دراسية|منحة|منح)\b"
        ),
        "scholarship",
    ),
]

# Study levels normalizations
STUDY_LEVEL_PATTERNS = [
    (re.compile(r"(?i)\b(phd|ph\.d|doctorate|doctoral|دكتوراه|دكتوراة)\b"), "PhD"),
    (
        re.compile(
            r"(?i)\b(master|masters|master's|msc|mba|postgraduate|graduate|ماجستير)\b"
        ),
        "Master",
    ),
    (
        re.compile(
            r"(?i)\b(bachelor|bachelors|bachelor's|bsc|undergraduate|undergrad|بكالوريوس|جامعي)\b"
        ),
        "Bachelor",
    ),
    (
        re.compile(r"(?i)\b(postdoc|post-doctoral|postdoctoral|ما بعد الدكتوراه)\b"),
        "Postdoc",
    ),
    (re.compile(r"(?i)\b(diploma|certificate|دبلوم|دبلومة|شهادة)\b"), "Diploma"),
    (re.compile(r"(?i)\b(high[ -]?school|secondary|ثانوية|مدرسة)\b"), "High School"),
]


# Country name standardizations
COUNTRY_MAPPINGS = {
    "usa": "United States",
    "united states": "United States",
    "united states of america": "United States",
    "us": "United States",
    "america": "United States",
    "أمريكا": "United States",
    "امريكا": "United States",
    "الولايات المتحدة": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "بريطانيا": "United Kingdom",
    "المملكة المتحدة": "United Kingdom",
    "germany": "Germany",
    "deutschland": "Germany",
    "ألمانيا": "Germany",
    "المانيا": "Germany",
    "canada": "Canada",
    "كندا": "Canada",
    "australia": "Australia",
    "أستراليا": "Australia",
    "استراليا": "Australia",
    "turkey": "Turkey",
    "türkiye": "Turkey",
    "turkiye": "Turkey",
    "تركيا": "Turkey",
    "france": "France",
    "فرنسا": "France",
    "italy": "Italy",
    "إيطاليا": "Italy",
    "ايطاليا": "Italy",
    "japan": "Japan",
    "اليابان": "Japan",
    "china": "China",
    "الصين": "China",
    "switzerland": "Switzerland",
    "سويسرا": "Switzerland",
    "netherlands": "Netherlands",
    "holland": "Netherlands",
    "هولندا": "Netherlands",
    "belgium": "Belgium",
    "بلجيكا": "Belgium",
    "sweden": "Sweden",
    "السويد": "Sweden",
    "saudi arabia": "Saudi Arabia",
    "ksa": "Saudi Arabia",
    "السعودية": "Saudi Arabia",
    "المملكة العربية السعودية": "Saudi Arabia",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
    "الإمارات": "United Arab Emirates",
    "الامارات": "United Arab Emirates",
    "qatar": "Qatar",
    "قطر": "Qatar",
    "egypt": "Egypt",
    "مصر": "Egypt",
    "mauritius": "Mauritius",
    "موريشيوس": "Mauritius",
    "new zealand": "New Zealand",
    "نيوزيلندا": "New Zealand",
    "singapore": "Singapore",
    "سنغافورة": "Singapore",
    "ireland": "Ireland",
    "أيرلندا": "Ireland",
    "ايرلندا": "Ireland",
}

REMOTE_KEYWORDS = re.compile(
    r"(?i)\b(remote|online|virtual|distance learning|عن بعد|أونلاين|اونلاين|افتراضي)\b"
)


class NormalizationService:
    """يقوم بتوحيد قيم الحقول المستخرجة إلى معايير وقيم قياسية متفق عليها."""

    def normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)

        # 1. Normalize opportunity_type
        normalized["opportunity_type"] = self.normalize_opportunity_type(
            normalized.get("opportunity_type"),
            search_text=f"{normalized.get('title', '')} {normalized.get('description', '')}",
        )

        # 2. Normalize funding_type
        normalized["funding_type"] = self.normalize_funding_type(
            normalized.get("funding_type"),
            search_text=f"{normalized.get('title', '')} {normalized.get('description', '')}",
        )

        # 3. Normalize study_levels
        normalized["study_levels"] = self.normalize_study_levels(
            normalized.get("study_levels") or [],
            search_text=f"{normalized.get('title', '')} {normalized.get('description', '')}",
        )

        # 4. Normalize country
        normalized["country"] = self.normalize_country(
            normalized.get("country"),
            search_text=f"{normalized.get('location', '')} {normalized.get('title', '')}",
        )

        # 5. Normalize is_remote
        normalized["is_remote"] = self.detect_is_remote(
            normalized.get("is_remote"),
            search_text=f"{normalized.get('title', '')} {normalized.get('location', '')} {normalized.get('description', '')}",
        )

        # 6. Normalize fields of study
        normalized["fields_of_study"] = self.normalize_fields_of_study(
            normalized.get("fields_of_study") or []
        )

        return normalized

    def normalize_funding_type(
        self, value: str | None, search_text: str = ""
    ) -> str | None:
        if value:
            text = value.lower().replace("_", " ").strip()
            for pattern, standard in FUNDING_MAPPINGS:
                if pattern.search(text):
                    return standard

        if search_text:
            text_s = search_text.lower().replace("_", " ").strip()
            for pattern, standard in FUNDING_MAPPINGS:
                if pattern.search(text_s):
                    return standard

        return None

    def normalize_opportunity_type(
        self, value: str | None, search_text: str = ""
    ) -> str:
        if value:
            text = value.lower().replace("_", " ").strip()
            for pattern, standard in OPPORTUNITY_TYPE_MAPPINGS:
                if pattern.search(text):
                    return standard

        if search_text:
            text_s = search_text.lower().replace("_", " ").strip()
            for pattern, standard in OPPORTUNITY_TYPE_MAPPINGS:
                if pattern.search(text_s):
                    return standard

        return "scholarship"

    def normalize_study_levels(
        self, levels: list[str], search_text: str = ""
    ) -> list[str]:
        found_levels = set()

        for lvl in levels:
            for pattern, standard in STUDY_LEVEL_PATTERNS:
                if pattern.search(str(lvl)):
                    found_levels.add(standard)

        if not found_levels and search_text:
            for pattern, standard in STUDY_LEVEL_PATTERNS:
                if pattern.search(search_text):
                    found_levels.add(standard)

        # Preserve canonical order: High School, Diploma, Bachelor, Master, PhD, Postdoc
        level_order = ["High School", "Diploma", "Bachelor", "Master", "PhD", "Postdoc"]
        return [lvl for lvl in level_order if lvl in found_levels]

    def normalize_country(self, value: str | None, search_text: str = "") -> str | None:
        if value:
            val_clean = value.strip().lower()
            if val_clean in COUNTRY_MAPPINGS:
                return COUNTRY_MAPPINGS[val_clean]
            for key, standard in COUNTRY_MAPPINGS.items():
                if key in val_clean:
                    return standard

        if search_text:
            search_clean = search_text.lower()
            for key, standard in COUNTRY_MAPPINGS.items():
                if re.search(rf"\b{re.escape(key)}\b", search_clean):
                    return standard

        return value.strip() if value else None

    def detect_is_remote(
        self, is_remote_val: bool | None, search_text: str = ""
    ) -> bool:
        if is_remote_val is True:
            return True
        if search_text and REMOTE_KEYWORDS.search(search_text):
            return True
        return False

    def normalize_fields_of_study(self, fields: list[str]) -> list[str]:
        cleaned_fields = []
        for field in fields:
            if not field:
                continue
            item = field.strip().title()
            if item and item not in cleaned_fields:
                cleaned_fields.append(item)
        return cleaned_fields
