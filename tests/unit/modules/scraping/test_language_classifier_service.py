from src.modules.scraping.services.language_classifier_service import (
    UNDETERMINED_LANGUAGE,
    LanguageClassifierService,
    OpportunityLanguageResult,
)


# [OMA-W005-T033] Test statistical n-gram classification on Arabic and English texts
def test_classify_text_arabic_and_english():
    """Protects UC-04 & TEST-04: Verifies offline statistical classification identifies Arabic and English."""
    service = LanguageClassifierService()

    # Arabic scholarship announcement
    ar_text = (
        "منحة جامعة الملك فهد للبترول والمعادن لدراسة الماجستير والدكتوراه "
        "مفتوحة الآن لجميع الطلاب الدوليين وتشمل تغطية مالية كاملة وراتب شهري."
    )
    lang_ar, conf_ar = service.classify_text(ar_text)
    assert lang_ar == "ar"
    assert 0.50 <= conf_ar <= 1.0

    # English scholarship announcement
    en_text = (
        "The Rhodes Scholarship is a fully funded postgraduate award "
        "enabling talented young people from around the world to study at the University of Oxford."
    )
    lang_en, conf_en = service.classify_text(en_text)
    assert lang_en == "en"
    assert 0.50 <= conf_en <= 1.0


# [OMA-W005-T033] Test statistical classification on French and German opportunity texts
def test_classify_text_french_and_german():
    """Protects Section 3.2: Verifies multilingual statistical classification on European scholarship portals."""
    service = LanguageClassifierService()

    # French scholarship announcement
    fr_text = (
        "Le programme de bourses Eiffel est un outil développé par le Ministère "
        "de l'Europe et des Affaires étrangères afin de permettre aux établissements français "
        "d'attirer les meilleurs étudiants étrangers dans des formations diplômantes."
    )
    lang_fr, conf_fr = service.classify_text(fr_text)
    assert lang_fr == "fr"
    assert 0.50 <= conf_fr <= 1.0

    # German scholarship announcement
    de_text = (
        "Das DAAD-Stipendienprogramm bietet ausländischen Studierenden und "
        "Graduierten die Möglichkeit, ein Studium oder eine Promotion an einer deutschen Hochschule zu absolvieren."
    )
    lang_de, conf_de = service.classify_text(de_text)
    assert lang_de == "de"
    assert 0.50 <= conf_de <= 1.0


# [OMA-W005-T035] Test confidence score normalization and threshold enforcement (< 0.50 -> "und")
def test_confidence_threshold_undetermined():
    """Protects FR-020 & Section 3.2: Text yielding confidence strictly below 0.50 is tagged as 'und'."""
    service = LanguageClassifierService(confidence_threshold=0.50)

    # Empty, whitespace, numeric, or non-alphabetical text
    assert service.classify_text("") == (UNDETERMINED_LANGUAGE, 0.0)
    assert service.classify_text("   \n\t  ") == (UNDETERMINED_LANGUAGE, 0.0)
    assert service.classify_text("1234567890 999") == (
        UNDETERMINED_LANGUAGE,
        0.0,
    )
    assert service.classify_text(None) == (UNDETERMINED_LANGUAGE, 0.0)

    # HTML tags are stripped during clean_text
    html_arabic = "<p><span>منحة الماجستير الممولة بالكامل للطلاب المتميزين</span></p>"
    lang_clean, conf_clean = service.classify_text(html_arabic)
    assert lang_clean == "ar"
    assert conf_clean >= 0.50


# [OMA-W005-T035] Test confidence score bounded strictly in [0.0, 1.0]
def test_confidence_score_bounds():
    """Protects domain invariant: Confidence score is mathematically normalized within [0.0, 1.0]."""
    service = LanguageClassifierService()

    samples = [
        "Fully funded scholarship at Stanford University.",
        "برنامج تدريب وبحث علمي في الرياض.",
        "abc",
        "Hello World 2026",
    ]

    for sample in samples:
        _, conf = service.classify_text(sample, enforce_threshold=False)
        assert 0.0 <= conf <= 1.0


# [OMA-W005-T039] Test independent title and body classification
def test_classify_opportunity_independent():
    """Protects UC-04 & Section 3.2: Independently classifies title and body and derives overall language."""
    service = LanguageClassifierService()

    # Bilingual case: Arabic Title, English Body
    ar_title = "منحة جامعة أكسفورد للدراسات العليا"
    en_body = (
        "The Oxford Clarendon Fund provides fully funded scholarships "
        "covering course fees and a living stipend for outstanding graduate scholars."
    )

    result = service.classify_opportunity(title=ar_title, description=en_body)

    assert isinstance(result, OpportunityLanguageResult)
    assert result.title_language == "ar"
    assert result.title_confidence >= 0.50
    assert result.body_language == "en"
    assert result.body_confidence >= 0.50
    # Overall language prefers body when decisive
    assert result.overall_language == "en"
    assert result.is_low_confidence is False

    # Dictionary conversion
    res_dict = result.to_dict()
    assert res_dict["title_language"] == "ar"
    assert res_dict["body_language"] == "en"
    assert res_dict["overall_language"] == "en"


# [OMA-W005-T039] Test opportunity classification when body is missing or short
def test_classify_opportunity_fallback_to_title():
    """Protects Section 3.2: Falls back to title when body description is absent or undetermined."""
    service = LanguageClassifierService()

    ar_title = "منحة جامعة الملك عبد الله للعلوم والتقنية"
    result = service.classify_opportunity(title=ar_title, description="")

    assert result.title_language == "ar"
    assert result.body_language == UNDETERMINED_LANGUAGE
    assert result.overall_language == "ar"
    assert result.is_low_confidence is False
