import httpx
import pytest

from src.modules.infrastructure.http.base_http_client import BaseHttpClient
from src.modules.scraping.adapters.scholars4dev_adapter import Scholars4DevAdapter


class TestScholars4DevAdapter:
    def test_source_name_and_base_url(self):
        adapter = Scholars4DevAdapter()
        assert adapter.source_name == "scholars4dev"
        assert adapter.base_url == "https://www.scholars4dev.com"

    @pytest.mark.asyncio
    async def test_fetch_html_listings(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
            <body>
                <div class="post">
                    <h2><a href="https://www.scholars4dev.com/101/daad-scholarships-germany/">DAAD Scholarships in Germany for Development</a></h2>
                    <div class="entry">
                        <p><strong>Host Institution:</strong> German Universities</p>
                        <p><strong>Target group:</strong> Developing country graduates. Master and PhD degrees. Fully Funded.</p>
                        <p><strong>Deadline:</strong> Aug-Oct 2026</p>
                    </div>
                </div>
                <div class="post">
                    <h2><a href="https://www.scholars4dev.com/102/australia-awards-scholarships/">Australia Awards Scholarships</a></h2>
                    <div class="entry">
                        <p><strong>Host Institution:</strong> Australian Universities</p>
                        <p><strong>Target group:</strong> Undergraduate and Postgraduate students. Full tuition fee, travel allowance.</p>
                        <p><strong>Deadline:</strong> 30 April 2026</p>
                    </div>
                </div>
            </body>
        </html>
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=sample_html)

        transport = httpx.MockTransport(handler)
        http_client = BaseHttpClient(client=httpx.AsyncClient(transport=transport))

        adapter = Scholars4DevAdapter(http_client=http_client)
        items = await adapter.fetch(limit=2)

        assert len(items) == 2
        assert "DAAD Scholarships" in items[0]["title"]
        assert "Australia Awards" in items[1]["title"]

    def test_parse_scholars4dev_item(self):
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "Gates Cambridge Scholarships for International Students (UK)",
            "summary": "University of Cambridge offers full-cost scholarships for postgraduate study (Masters and PhD). Deadline: 5 December 2026.",
            "content": "<p><strong>Host Institution:</strong></p><p>University of Cambridge</p><p><strong>Study in:</strong></p><p>UK</p><p>Fully funded scholarship covering tuition, maintenance allowance, airfare.</p>",
            "link": "https://www.scholars4dev.com/3313/gates-cambridge-scholarships-for-international-students/",
        }

        parsed = adapter.parse(raw_item)

        assert "Gates Cambridge" in parsed["title"]
        assert "Master" in parsed["study_levels"]
        assert "PhD" in parsed["study_levels"]
        assert parsed["funding_type"] == "fully_funded"
        assert parsed["country"] == "UK"
        assert parsed["organization"] == "University of Cambridge"
        assert "5 December 2026" in parsed["deadline"]

    def test_funding_type_default_is_none_when_no_keywords(self):
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "Generic University Award",
            "summary": "Some details about award.",
            "content": "<p>General information text with no funding mention.</p>",
            "link": "https://www.scholars4dev.com/123/generic-award/",
        }
        parsed = adapter.parse(raw_item)
        assert parsed["funding_type"] is None

    def test_fellowship_does_not_falsely_mark_phd(self):
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "Humphrey Fellowship Program",
            "summary": "Mid-career professional fellowship program.",
            "content": "<p>Non-degree fellowship program.</p>",
            "link": "https://www.scholars4dev.com/456/fellowship/",
        }
        parsed = adapter.parse(raw_item)
        assert "PhD" not in parsed["study_levels"]

    def test_scholars4dev_eligibility_extraction_both_target_group_and_eligibility(
        self,
    ):
        """Test extracting both Target group and Eligibility sections into eligibility_text."""
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "Swedish Institute Scholarships for Global Professionals (SISGP)",
            "content": """
                <p><strong>Target group:</strong></p>
                <p>Students from the following countries: Armenia, Azerbaijan, Bangladesh, Bolivia, Brazil, Cambodia, Colombia, Ecuador, Egypt, Ethiopia, Georgia, Ghana, Guatemala.</p>
                <p><strong>Scholarship value/inclusions/duration:</strong></p>
                <p>Full tuition fee coverage and living stipend of SEK 12,000/month.</p>
                <p><strong>Eligibility Requirements:</strong></p>
                <p>To be eligible for SISGP, you must:</p>
                <ul>
                    <li>Have a minimum of 3,000 hours of demonstrated work experience</li>
                    <li>Be a citizen of an eligible country</li>
                    <li>Apply for an eligible master's programme</li>
                </ul>
                <p><strong>Application instructions:</strong></p>
                <p>Apply via the official portal.</p>
            """,
            "link": "https://www.scholars4dev.com/5295/sweden-scholarships/",
        }

        parsed = adapter.parse(raw_item)
        assert "eligibility" in parsed
        elig = parsed["eligibility"]
        assert "eligibility_text" in elig
        text = elig["eligibility_text"]

        assert "Target group: Students from the following countries:" in text
        assert "Armenia, Azerbaijan, Bangladesh" in text
        assert "Eligibility:" in text
        assert "minimum of 3,000 hours" in text
        assert "eligible master's programme" in text

        # Assert no pollution from adjacent sections
        assert "Full tuition fee coverage" not in text
        assert "Apply via the official portal" not in text

    def test_scholars4dev_eligibility_extraction_target_group_only(self):
        """Test extracting Target group when Eligibility section is not present."""
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "Swiss Government Excellence Scholarships for Foreign Students",
            "content": """
                <p><strong>Host Institution(s):</strong></p>
                <p>Swiss Cantonal Universities, Federal Institutes of Technology</p>
                <p><strong>Target group:</strong></p>
                <p>International students from more than 180 countries worldwide.</p>
                <p><strong>Application instructions:</strong></p>
                <p>Contact Swiss embassy.</p>
            """,
            "link": "https://www.scholars4dev.com/3543/swiss-scholarships/",
        }

        parsed = adapter.parse(raw_item)
        text = parsed["eligibility"]["eligibility_text"]
        assert (
            "Target group: International students from more than 180 countries" in text
        )
        assert "Swiss Cantonal Universities" not in text
        assert "Contact Swiss embassy" not in text

    def test_scholars4dev_eligibility_missing_returns_empty_dict(self):
        """Test that a page without target group or eligibility sections returns empty dict."""
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "General Study Advice",
            "content": "<p>General article with no eligibility sections.</p>",
            "link": "https://www.scholars4dev.com/999/advice/",
        }

        parsed = adapter.parse(raw_item)
        assert parsed["eligibility"] == {}

    def test_scholars4dev_eligibility_does_not_pollute_with_metadata(self):
        """Test that Study in destination and host institution are not added to eligibility."""
        adapter = Scholars4DevAdapter()
        raw_item = {
            "title": "University of Sydney International Stipend Scholarship",
            "content": """
                <p><strong>Host Institution(s):</strong></p>
                <p>University of Sydney</p>
                <p><strong>Study in:</strong> Australia</p>
                <p><strong>Target group:</strong></p>
                <p>International students</p>
                <p><strong>Eligibility:</strong></p>
                <p>Commencing full-time Higher Degree by Research (HDR).</p>
            """,
            "link": "https://www.scholars4dev.com/2053/sydney-scholarship/",
        }

        parsed = adapter.parse(raw_item)
        text = parsed["eligibility"]["eligibility_text"]
        assert "Target group: International students" in text
        assert "Commencing full-time Higher Degree by Research" in text
        assert "Study in: Australia" not in text
        assert "Host Institution(s): University of Sydney" not in text
