from src.modules.scraping.services.normalization_service import NormalizationService


def test_normalization_service_study_levels():
    service = NormalizationService()

    # Aliases for Bachelor, Master, PhD
    levels = ["Undergraduate", "MSc", "Doctorate"]
    normalized = service.normalize_study_levels(levels)
    assert "Bachelor" in normalized
    assert "Master" in normalized
    assert "PhD" in normalized

    # Canonical ordering
    levels_unordered = ["PhD", "Bachelor", "High School", "Master"]
    ordered = service.normalize_study_levels(levels_unordered)
    assert ordered == ["High School", "Bachelor", "Master", "PhD"]


def test_normalization_service_funding_types():
    service = NormalizationService()
    assert service.normalize_funding_type("Full Funding") == "fully_funded"
    assert service.normalize_funding_type("100% Funded") == "fully_funded"
    assert service.normalize_funding_type("ممول بالكامل") == "fully_funded"
    assert service.normalize_funding_type("Tuition Fee Waiver") == "partially_funded"
    assert service.normalize_funding_type("Self Funded") == "unfunded"
    # Unknown funding must return None (not falsely default to partially_funded)
    assert service.normalize_funding_type("Unknown info") is None
    assert service.normalize_funding_type(None) is None


def test_normalization_service_countries():
    service = NormalizationService()
    assert service.normalize_country("USA") == "United States"
    assert service.normalize_country("United States of America") == "United States"
    assert service.normalize_country("أمريكا") == "United States"
    assert service.normalize_country("UK") == "United Kingdom"
    assert service.normalize_country("Great Britain") == "United Kingdom"
    assert service.normalize_country("Deutschland") == "Germany"
    assert service.normalize_country("قطر") == "Qatar"
    assert service.normalize_country("سويسرا") == "Switzerland"


def test_normalization_service_opportunity_types():
    service = NormalizationService()
    assert service.normalize_opportunity_type("Fellowship") == "fellowship"
    assert service.normalize_opportunity_type("Summer Internship") == "internship"
    assert service.normalize_opportunity_type("Bootcamp") == "training"
    assert service.normalize_opportunity_type("Exchange Program") == "exchange_program"
    assert service.normalize_opportunity_type("Hackathon") == "competition"
    assert service.normalize_opportunity_type("Research Grant") == "grant"
    assert service.normalize_opportunity_type("Scholarship") == "scholarship"


def test_normalization_service_remote_detection():
    service = NormalizationService()
    assert (
        service.detect_is_remote(
            None, search_text="This is a 100% remote online program"
        )
        is True
    )
    assert (
        service.detect_is_remote(None, search_text="On-campus study in Berlin") is False
    )


def test_normalization_service_no_false_positive_abbreviations():
    service = NormalizationService()
    # "ma", "ba", "bs" alone in search text should NOT produce Master or Bachelor
    normalized = service.normalize_study_levels(
        [], search_text="Candidates from MA or BA area with BS degrees"
    )
    assert "Master" not in normalized
    assert "Bachelor" not in normalized
