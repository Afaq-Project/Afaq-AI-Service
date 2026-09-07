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
            "content": "<p><strong>Host Institution:</strong> University of Cambridge</p><p>Fully funded scholarship covering tuition, maintenance allowance, airfare.</p>",
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
