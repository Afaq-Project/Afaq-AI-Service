from datetime import datetime

from src.modules.scraping.services.cleaning_service import CleaningService


def test_cleaning_service_basic_cleaning():
    service = CleaningService()
    raw_data = {
        "title": "  <b>Fully Funded</b> Masters Scholarship in Germany  ",
        "description": "<p>This is a comprehensive <i>scholarship</i> program.&nbsp;Apply today!</p>",
        "organization": " <span>DAAD Germany</span> ",
        "source_url": "https://example.com/scholarship-1",
        "deadline": "15 October 2026",
    }

    cleaned = service.clean(raw_data)
    assert cleaned["title"] == "Fully Funded Masters Scholarship in Germany"
    assert (
        "This is a comprehensive scholarship program. Apply today!"
        in cleaned["description"]
    )
    assert cleaned["organization"] == "DAAD Germany"
    assert isinstance(cleaned["deadline"], datetime)
    assert cleaned["deadline"].month == 10
    assert cleaned["deadline"].day == 15
    assert cleaned["deadline"].year == 2026


def test_cleaning_service_application_url_extraction():
    service = CleaningService()
    raw_data = {
        "title": "CERN Summer Student Program",
        "description": """
            <p>Welcome to CERN summer student program.</p>
            <p><a href="https://careers.cern/apply-now" target="_blank">Click here to Apply Online</a></p>
            <p><a href="https://example.com/cern-post">Read more on our blog</a></p>
        """,
        "source_url": "https://example.com/cern-post",
    }

    cleaned = service.clean(raw_data)
    assert cleaned["application_url"] == "https://careers.cern/apply-now"
    assert cleaned["source_url"] == "https://example.com/cern-post"


def test_cleaning_service_deadline_from_description_text():
    service = CleaningService()
    raw_data = {
        "title": "University Scholarship",
        "description": "<p>Applications close on: 25 December 2026. Don't miss out.</p>",
        "source_url": "https://example.com/post",
    }

    cleaned = service.clean(raw_data)
    assert isinstance(cleaned["deadline"], datetime)
    assert cleaned["deadline"].month == 12
    assert cleaned["deadline"].day == 25


def test_cleaning_service_same_domain_internal_link_filtered():
    """Verify internal links on the same domain as source_url are skipped as application_url."""
    service = CleaningService()
    raw_data = {
        "title": "GrabScholarship Article",
        "description": """
            <p>Check out our related scholarship post:</p>
            <p><a href="https://grabscholarships.com/another-scholarship-post/">Apply for another scholarship here</a></p>
        """,
        "source_url": "https://grabscholarships.com/current-post/",
    }

    cleaned = service.clean(raw_data)
    assert cleaned["application_url"] is None
