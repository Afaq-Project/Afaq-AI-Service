from datetime import UTC, datetime

import pytest

from src.modules.scraping.adapters.almin7_adapter import Almin7Adapter
from src.modules.scraping.services.cleaning_service import CleaningService


class TestAlmin7DeadlineExtractionPositive:
    """Positive test cases where Almin7 detail HTML contains valid exact Type A deadlines."""

    @pytest.fixture
    def adapter(self) -> Almin7Adapter:
        return Almin7Adapter()

    @pytest.fixture
    def cleaning_service(self) -> CleaningService:
        return CleaningService()

    def test_extract_deadline_from_heading_section(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>المواعيد النهائية</h2>
            <p>15 مايو 2026</p>
            <h2>شروط القبول</h2>
            <p>شهادة البكالوريوس بمعدل جيد جداً.</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "15 مايو 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_h3_heading(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h3>الموعد النهائي</h3>
            <p>20 فبراير 2026</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "20 فبراير 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 2, 20, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_strong_labeled_paragraph(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <p><strong>الموعد النهائي:</strong> 15 مايو 2026</p>
            <p><strong>الجهة المانحة:</strong> جامعة إسطنبول</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "15 مايو 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_b_labeled_paragraph(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <p><b>آخر موعد للتقديم:</b> 10 أكتوبر 2026</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "10 أكتوبر 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 10, 10, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_list_item(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <ul>
                <li><strong>مكان الدراسة:</strong> ألمانيا</li>
                <li><strong>آخر موعد:</strong> 15 يوليو 2026</li>
            </ul>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "15 يوليو 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 7, 15, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_table_rows(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <table>
                <tr>
                    <td>الجهة المانحة</td>
                    <td>جامعة كامبريدج</td>
                </tr>
                <tr>
                    <td>الموعد النهائي</td>
                    <td>15 مايو 2026</td>
                </tr>
            </table>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "15 مايو 2026"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    def test_extract_deadline_with_eastern_arabic_numerals(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>الموعد النهائي</h2>
            <p>١٥ مايو ٢٠٢٦</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "١٥ مايو ٢٠٢٦"

        cleaned = cleaning_service.clean(detail)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 5, 15, 0, 0, tzinfo=UTC)

    def test_extract_deadline_from_unstructured_card_content(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        raw_card = {
            "title": "منحة جامعة أكسفورد 2026",
            "content": "<p>تفاصيل المنحة ممولة بالكامل. آخر موعد للتقديم: 25 ديسمبر 2026 لجميع الطلاب.</p>",
            "link": "https://almin7.com/scholarship/oxford-2026/",
        }
        parsed = adapter.parse(raw_card)
        assert "25 ديسمبر 2026" in parsed["deadline"]

        cleaned = cleaning_service.clean(parsed)
        assert isinstance(cleaned["deadline"], datetime)
        assert cleaned["deadline"] == datetime(2026, 12, 25, 0, 0, tzinfo=UTC)


class TestAlmin7DeadlineExtractionNegative:
    """Negative test cases ensuring non-exact, seasonal, variable, or missing deadlines return None."""

    @pytest.fixture
    def adapter(self) -> Almin7Adapter:
        return Almin7Adapter()

    @pytest.fixture
    def cleaning_service(self) -> CleaningService:
        return CleaningService()

    def test_month_only_deadline_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>الموعد النهائي</h2>
            <p>يونيو 2026</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] == "يونيو 2026"

        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None

    def test_seasonal_wording_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>المواعيد النهائية</h2>
            <p>يفتح باب التقديم في الربيع ويغلق خلال فصل الخريف.</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None

    def test_variable_wording_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>المواعيد النهائية</h2>
            <p>تختلف المواعيد النهائية للتقديم باختلاف الكلية والبرنامج المختار.</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None

    def test_rolling_year_round_wording_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <p><strong>آخر موعد للتقديم:</strong> التقديم متاح طوال العام</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None

    def test_competing_multiple_dates_without_single_deadline_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>المواعيد النهائية</h2>
            <p>الجولة الأولى: 15 يناير 2026 أو الجولة الثانية: 1 مارس 2026</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None

    def test_missing_deadline_section_returns_none(
        self, adapter: Almin7Adapter, cleaning_service: CleaningService
    ) -> None:
        html = """
        <div class="al7-single-content">
            <h2>عن المنحة</h2>
            <p>منحة دراسية لدراسة البكالوريوس في ماليزيا.</p>
        </div>
        """
        detail = adapter._parse_detail_html(html)
        assert detail["deadline"] is None

        cleaned = cleaning_service.clean(detail)
        assert cleaned["deadline"] is None
