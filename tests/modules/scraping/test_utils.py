from src.modules.scraping.utils.date_parser import (
    extract_deadline_from_text,
    parse_date,
)
from src.modules.scraping.utils.text_cleaner import (
    clean_html,
    clean_text,
    extract_emails,
    extract_first_url,
    extract_urls,
)


class TestUtils:
    def test_clean_html(self):
        html_input = """
        <div>
            <h1>Scholarship Title</h1>
            <p>Here is some <script>alert('xss')</script> text with &amp; entities.</p>
            <ul>
                <li>Benefit 1</li>
                <li>Benefit 2</li>
            </ul>
        </div>
        """
        cleaned = clean_html(html_input)
        assert "alert('xss')" not in cleaned
        assert "&amp;" not in cleaned
        assert "Scholarship Title" in cleaned
        assert "Benefit 1" in cleaned
        assert "Benefit 2" in cleaned

    def test_clean_text(self):
        raw = "  Hello   World &amp;  Levora \xa0 Project \u200b "
        assert clean_text(raw) == "Hello World & Levora Project"

    def test_extract_urls_and_emails(self):
        text = "Visit https://almin7.com or http://daad.de/app and contact info@example.com."
        urls = extract_urls(text)
        assert "https://almin7.com" in urls
        assert "http://daad.de/app" in urls
        assert extract_first_url(text) == "https://almin7.com"

        emails = extract_emails(text)
        assert emails == ["info@example.com"]

    def test_parse_date_various_formats(self):
        # ISO format
        dt1 = parse_date("2026-10-15T12:00:00Z")
        assert dt1 is not None
        assert dt1.year == 2026
        assert dt1.month == 10
        assert dt1.day == 15

        # English formatted string
        dt2 = parse_date("15 October 2026")
        assert dt2 is not None
        assert dt2.year == 2026
        assert dt2.month == 10
        assert dt2.day == 15

        # Arabic formatted string
        dt3 = parse_date("31 ديسمبر 2026")
        assert dt3 is not None
        assert dt3.year == 2026
        assert dt3.month == 12
        assert dt3.day == 31

    def test_extract_deadline_from_text(self):
        text_en = "The application closes on 25 November 2026 for all students."
        deadline_en = extract_deadline_from_text(text_en)
        assert deadline_en is not None
        assert deadline_en.year == 2026
        assert deadline_en.month == 11
        assert deadline_en.day == 25

        text_ar = "آخر موعد للتقديم: 15 أكتوبر 2026 لا يتم قبول طلبات بعد هذا التاريخ."
        deadline_ar = extract_deadline_from_text(text_ar)
        assert deadline_ar is not None
        assert deadline_ar.year == 2026
        assert deadline_ar.month == 10
        assert deadline_ar.day == 15
